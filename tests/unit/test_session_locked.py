"""session_locked reads the session flags from WTSINFOEXW, with Windows' answer faked."""

from __future__ import annotations

import ctypes
from typing import Any

import pytest

from jarvis.platform import windows as win


class FakeWts:
    def __init__(self, flags: int, ok: bool = True) -> None:
        self.info = (ctypes.c_long * 6)(1, 0, 3, 0, flags, 0)
        self.ok = ok
        self.freed = 0

    def WTSQuerySessionInformationW(
        self, server: Any, session: Any, kind: int, out: Any, size: Any
    ) -> bool:
        assert kind == win.WTS_SESSION_INFO_EX
        if self.ok:
            out._obj.contents = ctypes.cast(self.info, ctypes.POINTER(ctypes.c_long)).contents
        return self.ok

    def WTSFreeMemory(self, memory: Any) -> None:
        self.freed += 1


@pytest.mark.parametrize(("flags", "locked"), [(0, True), (1, False)])
def test_reads_the_lock_flag_and_frees_the_memory(
    monkeypatch: pytest.MonkeyPatch, flags: int, locked: bool
) -> None:
    fake = FakeWts(flags)
    monkeypatch.setattr(win, "wtsapi32", fake)
    assert win.session_locked() is locked
    assert fake.freed == 1


def test_an_unknown_state_is_an_error_not_a_guess(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeWts(-1)
    monkeypatch.setattr(win, "wtsapi32", fake)
    with pytest.raises(OSError, match="unknown lock state"):
        win.session_locked()
    assert fake.freed == 1


def test_a_failed_query_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(win, "wtsapi32", FakeWts(0, ok=False))
    with pytest.raises(OSError, match=r"."):
        win.session_locked()
