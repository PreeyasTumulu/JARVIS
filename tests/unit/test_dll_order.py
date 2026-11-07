"""WinRT first, onnxruntime second used to crash the process (R58). Each case runs in a fresh
interpreter, because a DLL loaded by an earlier test would hide the problem."""

from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32"
    or importlib.util.find_spec("onnxruntime") is None
    or importlib.util.find_spec("winrt") is None,
    reason="needs Windows, onnxruntime (the voice extra), and winrt",
)


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )


def test_notifications_then_piper_works_once_jarvis_is_imported() -> None:
    done = _run(
        "import jarvis, threading\n"
        "import winrt.windows.ui.notifications.management\n"
        "def speak():\n"
        "    import onnxruntime\n"  # what Piper loads on its first sentence, on a worker thread
        "t = threading.Thread(target=speak); t.start(); t.join(); print('ok')\n"
    )
    assert done.returncode == 0, done.stderr[-500:]
    assert done.stdout.strip() == "ok"


def test_the_runtime_jarvis_loads_is_the_system_one() -> None:
    done = _run(
        "import ctypes, jarvis\n"
        "k = ctypes.windll.kernel32\n"
        "k.GetModuleHandleW.restype = ctypes.c_void_p\n"
        "handle = k.GetModuleHandleW('msvcp140.dll')\n"
        "buf = ctypes.create_unicode_buffer(260)\n"
        "k.GetModuleFileNameW(ctypes.c_void_p(handle), buf, 260)\n"
        "print(buf.value)\n"
    )
    assert done.returncode == 0, done.stderr[-500:]
    assert "system32" in done.stdout.casefold()
