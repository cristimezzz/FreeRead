import socket
import subprocess
import sys
import threading
import time

import httpx

from freeread.main import watch_parent

SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_watchdog_fires_when_parent_exits():
    parent = subprocess.Popen(SLEEPER)
    fired = threading.Event()
    try:
        watch_parent(parent.pid, fired.set, interval=0.1)
        assert not fired.wait(0.5)
    finally:
        parent.kill()
        parent.wait()
    assert fired.wait(5)


def test_watchdog_fires_immediately_for_missing_parent():
    fired = threading.Event()
    watch_parent(_dead_pid(), fired.set, interval=0.1)
    assert fired.wait(5)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_core_exits_after_parent_killed():
    parent = subprocess.Popen(SLEEPER)
    port = _free_port()
    core = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "freeread.main",
            "--port",
            str(port),
            "--token",
            "t",
            "--parent-pid",
            str(parent.pid),
        ],
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                resp = httpx.get(
                    f"http://127.0.0.1:{port}/health", headers={"X-FreeRead-Token": "t"}
                )
                assert resp.json()["status"] == "ok"
                break
            except httpx.TransportError:
                assert core.poll() is None, "core exited before becoming healthy"
                assert time.monotonic() < deadline, "core did not become healthy"
                time.sleep(0.1)

        parent.kill()
        parent.wait()
        assert core.wait(timeout=10) is not None
    finally:
        if core.poll() is None:
            core.kill()
        if parent.poll() is None:
            parent.kill()
