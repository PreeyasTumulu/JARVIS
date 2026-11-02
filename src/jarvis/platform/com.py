"""One worker thread with COM initialized, for Windows APIs that need it (audio endpoints, UIA).

COM objects belong to the thread that created them, so every COM call goes through this single
thread instead of asyncio's general thread pool.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")

_executor: ThreadPoolExecutor | None = None


def _initialize() -> None:
    import comtypes

    comtypes.CoInitialize()


async def run_com(fn: Callable[..., T], *args: Any) -> T:
    """Run `fn(*args)` on the COM thread without blocking the event loop."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="jarvis-com", initializer=_initialize
        )
    return await asyncio.get_running_loop().run_in_executor(_executor, fn, *args)
