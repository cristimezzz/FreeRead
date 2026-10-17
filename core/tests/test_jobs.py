import asyncio

import pytest

from freeread.infra.db.models import JobRow
from freeread.infra.jobs.queue import JobStatus
from freeread.infra.jobs.worker import JobContext, JobWorker


async def wait_status(ctx, job_id, *statuses, timeout=5.0):
    async def poll():
        while (job := ctx.jobs.get(job_id)).status not in statuses:
            await asyncio.sleep(0.01)
        return job

    return await asyncio.wait_for(poll(), timeout)


@pytest.fixture
async def worker(ctx):
    ctx.bus.bind_loop(asyncio.get_running_loop())
    w = JobWorker(ctx.jobs, ctx.bus, poll_interval=0.05)
    yield w
    await w.stop()


async def test_job_runs_and_reports_progress(ctx, worker):
    seen = []

    async def handler(job_ctx: JobContext):
        seen.append(job_ctx.job.payload)
        await job_ctx.report(0.5, "half")
        assert ctx.jobs.get(job_ctx.job.id).message == "half"

    worker.register("demo", handler)
    await worker.start()
    job = ctx.jobs.enqueue("demo", {"x": 1})
    done = await wait_status(ctx, job.id, JobStatus.DONE)
    assert seen == [{"x": 1}]
    assert done.progress == 1.0 and done.attempts == 1 and done.finished_at


async def test_dependency_chain_runs_in_order(ctx, worker):
    order = []

    async def handler(job_ctx: JobContext):
        await asyncio.sleep(0.02)
        order.append(job_ctx.job.payload["name"])

    worker.register("step", handler, concurrency=4)
    a = ctx.jobs.enqueue("step", {"name": "import"})
    b = ctx.jobs.enqueue("step", {"name": "parse"}, depends_on=a.id)
    c = ctx.jobs.enqueue("step", {"name": "embed"}, depends_on=b.id)
    await worker.start()
    await wait_status(ctx, c.id, JobStatus.DONE)
    assert order == ["import", "parse", "embed"]


async def test_failed_dependency_cancels_dependents(ctx, worker):
    async def boom(job_ctx: JobContext):
        raise ValueError("bad pdf")

    async def ok(job_ctx: JobContext):
        pass

    worker.register("parse", boom)
    worker.register("embed", ok)
    a = ctx.jobs.enqueue("parse")
    b = ctx.jobs.enqueue("embed", depends_on=a.id)
    await worker.start()
    failed = await wait_status(ctx, a.id, JobStatus.FAILED)
    assert failed.error == "ValueError: bad pdf"
    cancelled = await wait_status(ctx, b.id, JobStatus.CANCELLED)
    assert a.id in cancelled.error


async def test_retry_until_max_attempts(ctx, worker):
    calls = 0

    async def flaky(job_ctx: JobContext):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("429")

    worker.register("translate", flaky, max_attempts=2)
    job = ctx.jobs.enqueue("translate")
    await worker.start()
    done = await wait_status(ctx, job.id, JobStatus.DONE)
    assert done.attempts == 2 and done.error is None


async def test_per_kind_concurrency_limit(ctx, worker):
    active = peak = 0

    async def heavy(job_ctx: JobContext):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1

    worker.register("parse", heavy, concurrency=1)
    jobs = [ctx.jobs.enqueue("parse") for _ in range(3)]
    await worker.start()
    for job in jobs:
        await wait_status(ctx, job.id, JobStatus.DONE)
    assert peak == 1


async def test_cancel_running_and_queued(ctx, worker):
    started = asyncio.Event()

    async def forever(job_ctx: JobContext):
        started.set()
        await asyncio.Event().wait()

    worker.register("long", forever)
    running = ctx.jobs.enqueue("long")
    queued = ctx.jobs.enqueue("other")  # 没有 handler，一直排队
    await worker.start()
    await asyncio.wait_for(started.wait(), 5)

    assert (await worker.cancel(running.id)).status == JobStatus.CANCELLED
    assert (await worker.cancel(queued.id)).status == JobStatus.CANCELLED
    assert worker.running_ids == set()


async def test_unregistered_kind_stays_queued(ctx, worker):
    job = ctx.jobs.enqueue("kg_extract")
    await worker.start()
    await asyncio.sleep(0.2)
    assert ctx.jobs.get(job.id).status == JobStatus.QUEUED


async def test_shutdown_requeues_and_restart_resumes(ctx, worker):
    started = asyncio.Event()
    finished = []

    async def slow(job_ctx: JobContext):
        started.set()
        await asyncio.sleep(10)

    worker.register("parse", slow)
    job = ctx.jobs.enqueue("parse")
    await worker.start()
    await asyncio.wait_for(started.wait(), 5)
    await worker.stop()
    assert ctx.jobs.get(job.id).status == JobStatus.QUEUED

    async def fast(job_ctx: JobContext):
        finished.append(job_ctx.job.id)

    w2 = JobWorker(ctx.jobs, ctx.bus, poll_interval=0.05)
    w2.register("parse", fast)
    await w2.start()
    try:
        done = await wait_status(ctx, job.id, JobStatus.DONE)
    finally:
        await w2.stop()
    assert finished == [job.id] and done.attempts == 2


async def test_recover_resets_running_jobs_after_crash(ctx):
    job = ctx.jobs.enqueue("parse")
    with ctx.sessions.begin() as s:
        s.get(JobRow, job.id).status = JobStatus.RUNNING
    assert ctx.jobs.recover() == 1
    assert ctx.jobs.get(job.id).status == JobStatus.QUEUED


async def test_job_events_are_published(ctx, worker):
    async def handler(job_ctx: JobContext):
        await job_ctx.report(0.3)

    worker.register("demo", handler)
    statuses = []
    async with ctx.bus.subscribe() as sub:
        await worker.start()
        job = ctx.jobs.enqueue("demo")
        while True:
            event = await asyncio.wait_for(sub.get(), 5)
            if event.data["id"] == job.id:
                statuses.append((event.data["status"], event.data["progress"]))
                if event.data["status"] == JobStatus.DONE:
                    break
    assert statuses == [("queued", 0.0), ("running", 0.0), ("running", 0.3), ("done", 1.0)]


async def test_cancel_after_handler_returns_still_marks_done(ctx, worker, monkeypatch):
    # handler 已返回、DONE 尚未写库时被取消，任务不能停在 running。
    in_finish = asyncio.Event()
    release = asyncio.Event()
    loop = asyncio.get_running_loop()
    original = worker._finish_done

    def slow_finish(job_id):
        loop.call_soon_threadsafe(in_finish.set)
        asyncio.run_coroutine_threadsafe(release.wait(), loop).result()
        original(job_id)

    monkeypatch.setattr(worker, "_finish_done", slow_finish)

    async def quick(job_ctx: JobContext):
        pass

    worker.register("quick", quick)
    job = ctx.jobs.enqueue("quick")
    await worker.start()
    await asyncio.wait_for(in_finish.wait(), 5)
    cancel = asyncio.create_task(worker.cancel(job.id))
    await asyncio.sleep(0.05)
    release.set()
    await asyncio.wait_for(cancel, 5)
    assert ctx.jobs.get(job.id).status == JobStatus.DONE
    assert worker.running_ids == set()
