"""Jarvis: a local-first, voice-controlled desktop assistant for Windows 11."""

import sys

__version__ = "1.14.0"


def _load_the_system_cpp_runtime() -> None:
    """Load Windows' own msvcp140.dll before any package brings an older copy (R58).

    The winrt packages ship their own msvcp140.dll. Windows keeps one module per DLL name in a
    process, so once that copy is loaded, onnxruntime (Piper, the wake word) binds to it and
    crashes the whole process with an access violation. Loaded first, the system copy is the
    one everybody shares. A PC without the Visual C++ runtime simply skips this.
    """
    import contextlib
    import ctypes

    with contextlib.suppress(OSError):
        ctypes.WinDLL("msvcp140.dll")


if sys.platform == "win32":
    _load_the_system_cpp_runtime()
