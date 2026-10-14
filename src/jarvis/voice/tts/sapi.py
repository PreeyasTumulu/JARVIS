"""Windows SAPI voice through PowerShell's System.Speech.

No extra dependencies, and each utterance is its own process, so stopping is instant (kill it).
The text is passed base64-encoded so quoting and non-ASCII characters cannot break the script.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import subprocess

_SCRIPT = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.Rate = {rate}; "
    "$s.Speak([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')))"
)


class SapiTTS:
    def __init__(self, rate: int = 0) -> None:
        self._rate = max(-10, min(10, rate))
        self._proc: asyncio.subprocess.Process | None = None

    async def speak(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        script = _SCRIPT.format(rate=self._rate, payload=payload)
        proc = await asyncio.create_subprocess_exec(
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self._proc = proc
        try:
            _, stderr = await proc.communicate()
        except asyncio.CancelledError:
            _kill(proc)
            raise
        finally:
            self._proc = None
        if proc.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[:200]
            raise RuntimeError(f"Windows speech failed: {detail or proc.returncode}")

    async def stop(self) -> None:
        if self._proc is not None:
            _kill(self._proc)


def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
