import asyncio
import json
import sys
from pathlib import Path

import pytest

from freeread.infra.parsers.base import ParserCaps
from freeread.infra.parsers.resident import ResidentEngineParser, WorkerError

FAKE_WORKER = Path(__file__).parent / "fixtures" / "workers" / "fake_worker.py"
CAPS = ParserCaps(formulas=False, tables=False, ocr=False, needs_gpu=False)


def make_parser(tmp_path, idle_timeout=60.0):
    return ResidentEngineParser(
        "fake",
        CAPS,
        [sys.executable, str(FAKE_WORKER)],
        log_path=tmp_path / "logs" / "fake-worker.log",
        options={"effort": "medium"},
        idle_timeout=idle_timeout,
    )


def pdf(tmp_path, name):
    p = tmp_path / name
    p.write_bytes(b"%PDF-1.4")
    return p


def pid_of(out_dir: Path) -> int:
    return json.loads((out_dir / "result.json").read_text())["pid"]


async def test_reuses_one_process_and_passes_options(tmp_path):
    parser = make_parser(tmp_path)
    seen = []
    try:
        raw1 = await parser.parse(
            pdf(tmp_path, "a.pdf"), tmp_path / "o1", lambda p, m: seen.append(p)
        )
        raw2 = await parser.parse(pdf(tmp_path, "b.pdf"), tmp_path / "o2", lambda p, m: None)
    finally:
        await parser.close()
    assert raw1.engine == "fake" and raw1.engine_version == "9.9"
    assert pid_of(raw1.raw_dir) == pid_of(raw2.raw_dir)
    assert json.loads((raw1.raw_dir / "result.json").read_text())["effort"] == "medium"
    assert seen[0] == 0.0 and seen[-1] == 1.0
    assert not parser.running
    # 引擎打到 stdout 的内容进了日志，没有破坏协议
    assert "noise on stdout" in (tmp_path / "logs" / "fake-worker.log").read_text()


async def test_error_is_reported_and_worker_restarts(tmp_path):
    parser = make_parser(tmp_path)
    try:
        with pytest.raises(WorkerError, match="ValueError: cannot parse"):
            await parser.parse(pdf(tmp_path, "bad.pdf"), tmp_path / "o1", lambda p, m: None)
        raw = await parser.parse(pdf(tmp_path, "ok.pdf"), tmp_path / "o2", lambda p, m: None)
        assert (raw.raw_dir / "engine.json").is_file()
    finally:
        await parser.close()


async def test_crash_raises_and_next_call_restarts(tmp_path):
    parser = make_parser(tmp_path)
    try:
        with pytest.raises(WorkerError, match="exited with 3"):
            await parser.parse(pdf(tmp_path, "crash.pdf"), tmp_path / "o1", lambda p, m: None)
        assert not parser.running
        raw = await parser.parse(pdf(tmp_path, "ok.pdf"), tmp_path / "o2", lambda p, m: None)
        assert pid_of(raw.raw_dir) > 0
    finally:
        await parser.close()


async def test_cancel_kills_worker(tmp_path):
    parser = make_parser(tmp_path)
    task = asyncio.create_task(
        parser.parse(pdf(tmp_path, "slow.pdf"), tmp_path / "o1", lambda p, m: None)
    )
    while not parser.running:
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not parser.running
    await parser.close()


async def test_idle_timeout_stops_worker(tmp_path):
    parser = make_parser(tmp_path, idle_timeout=0.2)
    try:
        await parser.parse(pdf(tmp_path, "a.pdf"), tmp_path / "o1", lambda p, m: None)
        assert parser.running
        await asyncio.sleep(1.0)
        assert not parser.running
    finally:
        await parser.close()
