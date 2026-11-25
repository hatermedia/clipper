from __future__ import annotations

import sys
import threading
import time

import pytest

from clipper import ffmpeg


def _wait_for_active(count: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ffmpeg.active_process_count() == count:
            return True
        time.sleep(0.01)
    return False


def test_terminate_active_processes_stops_child_and_clears_registry() -> None:
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            ffmpeg._run([sys.executable, "-c", "import time; time.sleep(30)"])
        except BaseException as exc:  # pragma: no cover - diagnostic path
            errors.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        assert _wait_for_active(1), "child process was not registered"
        ffmpeg.terminate_active_processes()
        thread.join(5.0)
        assert not thread.is_alive()
        assert not errors
        assert ffmpeg.active_process_count() == 0
    finally:
        ffmpeg.terminate_active_processes()


def test_timeout_kills_child_and_does_not_leak() -> None:
    with pytest.raises(ffmpeg.FFmpegError, match="timed out"):
        ffmpeg._run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.2,
        )
    assert ffmpeg.active_process_count() == 0
