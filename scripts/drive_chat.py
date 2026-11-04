"""Drive a real `jarvis chat` through pipes for hand tests (docs/HANDTESTS.md).

Usage: uv run python scripts/drive_chat.py <steps.json> <scratch folder>

The scratch folder gets its own data folder (`ld`, used as LOCALAPPDATA) and must hold a
config copy in `cfg` (used as JARVIS_CONFIG_DIR), so a test never touches your own data.

Steps, in order:
  {"send": "text"}                  wait for the next "you >" prompt, then type the text
                                    (add "nowait": true when the prompt was already seen)
  {"answer": "y"}                   wait for a confirmation or a question, then answer it
  {"wait_for": "regex", "timeout": 200}
  {"sleep": seconds}
  {"shell": "powershell command"}   a side action, for example Set-Clipboard
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO

REPO = Path(__file__).resolve().parents[1]

_buf: list[str] = []
_lock = threading.Lock()


def _reader(stream: IO[str]) -> None:
    # Character by character: the prompts do not end with a newline.
    for char in iter(lambda: stream.read(1), ""):
        with _lock:
            _buf.append(char)
        sys.stdout.write(char)
        if char in "\n ":
            sys.stdout.flush()


def _output() -> str:
    with _lock:
        return "".join(_buf)


def _wait_for(pattern: str, mark: int, timeout: float) -> int:
    end = time.time() + timeout
    rx = re.compile(pattern)
    while time.time() < end:
        found = rx.search(_output(), mark)
        if found:
            return found.end()
        time.sleep(0.2)
    print(f"\n!! timed out waiting for {pattern!r}")
    return len(_output())


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    steps = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    scratch = Path(sys.argv[2]).resolve()
    (scratch / "ld").mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        LOCALAPPDATA=str(scratch / "ld"),
        JARVIS_CONFIG_DIR=str(scratch / "cfg"),
        PYTHONIOENCODING="utf-8",
        UV_NO_SYNC="1",
        COLUMNS="200",
    )
    proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "jarvis", "chat"],
        cwd=REPO,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.stdin is not None and proc.stdout is not None
    threading.Thread(target=_reader, args=(proc.stdout,), daemon=True).start()
    mark = 0
    try:
        for step in steps:
            timeout = step.get("timeout", 240)
            if "send" in step:
                if not step.get("nowait"):
                    mark = _wait_for(r"you > ", mark, timeout)
                print(f"[[send]] {step['send']}")
                proc.stdin.write(step["send"] + "\n")
                proc.stdin.flush()
            elif "answer" in step:
                mark = _wait_for(r"Allow\?|jarvis asks", mark, timeout)
                time.sleep(0.5)
                print(f"[[answer]] {step['answer']}")
                proc.stdin.write(step["answer"] + "\n")
                proc.stdin.flush()
            elif "wait_for" in step:
                mark = _wait_for(step["wait_for"], mark, timeout)
            elif "sleep" in step:
                time.sleep(step["sleep"])
            elif "shell" in step:
                subprocess.run(["powershell", "-NoProfile", "-Command", step["shell"]], check=False)
                print(f"[[shell]] {step['shell']}")
        _wait_for(r"you > ", mark, 240)
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            # uv leaves the Python child running if only the parent is stopped
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
