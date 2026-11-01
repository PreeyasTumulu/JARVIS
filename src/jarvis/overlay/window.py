"""The overlay process: a transparent window over everything that never takes a click or focus.

Started by `client.py`, it reads JSON lines from stdin and exits when the pipe closes, so it cannot
outlive Jarvis. While hidden it draws nothing and only waits.

These window styles were checked on this laptop before anything was built (docs/RISKS.md R53):
WS_EX_LAYERED with WS_EX_TRANSPARENT sends every click to the window below, WS_EX_NOACTIVATE and
SW_SHOWNOACTIVATE keep the focus where it was, which WhatsApp sends and typing depend on, and
WDA_EXCLUDEFROMCAPTURE keeps it out of screenshots, screen shares, and Jarvis's own screen reading.
"""

from __future__ import annotations

import ctypes
import json
import logging
import queue
import sys
import threading
import time
from ctypes import wintypes
from typing import Any

import glfw
import moderngl

from jarvis.overlay import EXIT_NO_GRAPHICS
from jarvis.overlay.card import CardText, render_card
from jarvis.overlay.renderer import Renderer
from jarvis.overlay.scene import TAKEOVER_STATES, Scene

log = logging.getLogger(__name__)

GWL_EXSTYLE = -20
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x8, 0x20, 0x80
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x80000, 0x8000000
LWA_ALPHA = 0x2
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
WDA_EXCLUDEFROMCAPTURE = 0x11
SPI_GETCLIENTAREAANIMATION = 0x1042
QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE = 3, 4  # 5 is the normal desktop
HWND_TOPMOST = wintypes.HWND(-1)

HIDDEN_WAIT_S = 0.05
FRAME_S = 1 / 60
CARD_BIG_WIDTH = 1240
CARD_SMALL_WIDTH = 900
CARD_BIG_Y = 0.235  # the words' centre, as a share of the screen height from the bottom
CARD_SMALL_Y = 0.105

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND,
    wintypes.COLORREF,
    wintypes.BYTE,
    wintypes.DWORD,
]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [wintypes.UINT]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]


def animations_off() -> bool:
    """Windows' "Animation effects" setting. Off means no burst and a slow flow."""
    enabled = wintypes.BOOL(True)
    user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0)
    return not enabled.value


def screen_is_taken() -> bool:
    """A fullscreen game or a presentation: a topmost window could knock it out of fullscreen."""
    state = ctypes.c_int(0)
    result = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    return result == 0 and state.value in (QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE)


class Overlay:
    def __init__(self, config: dict[str, Any]) -> None:
        self.scene = Scene(
            mode=str(config.get("mode", "takeover")),
            max_dim=float(config.get("dim", 0.72)),
            calm=1.0 if animations_off() else 0.0,
        )
        self.max_visible_s = float(config.get("max_visible_s", 240))
        self.show_in_captures = bool(config.get("show_in_captures", False))
        self.text = CardText()
        self.hide_at: float | None = None
        self.last_message = 0.0
        self.shown = False
        self.card_dirty = False
        self._create_window()

    def _create_window(self) -> None:
        if not glfw.init():
            raise RuntimeError("GLFW could not start")
        monitor = glfw.get_primary_monitor()
        mode = glfw.get_video_mode(monitor)
        self.scale = mode.size.height / 1080
        # One pixel short of the monitor, so Windows does not treat this as a fullscreen app and
        # stop compositing what is behind it.
        width, height = mode.size.width, mode.size.height - 1
        glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, True)
        glfw.window_hint(glfw.DECORATED, False)
        glfw.window_hint(glfw.FLOATING, True)
        glfw.window_hint(glfw.FOCUSED, False)
        glfw.window_hint(glfw.FOCUS_ON_SHOW, False)
        glfw.window_hint(glfw.VISIBLE, False)
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        self.window = glfw.create_window(width, height, "Jarvis overlay", None, None)
        if not self.window:
            raise RuntimeError("OpenGL 3.3 with a transparent window is not available")
        glfw.make_context_current(self.window)
        # The window is composited, so it cannot tear, and waiting for vsync here spins a CPU core
        # in the driver. run() paces the frames with a sleep instead.
        glfw.swap_interval(0)
        self.renderer = Renderer(moderngl.create_context(), width, height)
        self.hwnd = wintypes.HWND(glfw.get_win32_window(self.window))
        style = user32.GetWindowLongPtrW(self.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(
            self.hwnd,
            GWL_EXSTYLE,
            style
            | WS_EX_LAYERED
            | WS_EX_TRANSPARENT
            | WS_EX_NOACTIVATE
            | WS_EX_TOOLWINDOW
            | WS_EX_TOPMOST,
        )
        user32.SetLayeredWindowAttributes(self.hwnd, 0, 255, LWA_ALPHA)  # or it never appears
        if not self.show_in_captures:
            user32.SetWindowDisplayAffinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE)
        glfw.set_window_pos(self.window, 0, 0)
        log.info("Overlay ready: %dx%d on %s", width, height, self.renderer.ctx.info["GL_RENDERER"])

    def handle(self, message: dict[str, Any]) -> None:
        self.last_message = time.monotonic()
        kind = message.get("t")
        if kind == "wake":
            self.hide_at = None
            self.text = CardText()
            self.card_dirty = True
            self._show()
            self.scene.wake()
        elif kind == "state":
            self.hide_at = None
            self.scene.set_state(str(message.get("state", "")))
            self.card_dirty = True
        elif kind == "level":
            self.scene.set_level(float(message.get("v", 0.0)))
        elif kind == "text":
            self.text = CardText(
                heading=str(message.get("heading", "")),
                body=str(message.get("body", "")),
                status=str(message.get("status", "")),
                tone=str(message.get("tone", "normal")),
            )
            self.card_dirty = True
        elif kind == "hide":
            self.hide_at = time.monotonic() + float(message.get("after", 0.0))

    def _show(self) -> None:
        if screen_is_taken():
            log.info("A fullscreen game or presentation is running; the overlay stays hidden")
            return
        if not self.shown:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            user32.SetWindowPos(
                self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
            )
            self.shown = True

    def _hide(self) -> None:
        if self.shown:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            self.shown = False

    def _upload_card(self) -> None:
        self.card_dirty = False
        text = self.text
        if not (text.heading or text.body or text.status):
            self.renderer.set_card(None, center_y_px=0)
            return
        big = self.scene.mode == "takeover" and self.scene.state in TAKEOVER_STATES
        width = round((CARD_BIG_WIDTH if big else CARD_SMALL_WIDTH) * self.scale)
        image = render_card(text, width=width, big=big, scale=self.scale)
        share = CARD_BIG_Y if big else CARD_SMALL_Y
        self.renderer.set_card(image, center_y_px=self.renderer.height * share)

    def run(self, inbox: queue.Queue[dict[str, Any] | None]) -> None:
        previous = time.perf_counter()
        while True:
            try:
                while True:
                    message = inbox.get_nowait()
                    if message is None:
                        return  # Jarvis closed the pipe
                    self.handle(message)
            except queue.Empty:
                pass
            now = time.monotonic()
            if self.scene.showing and (
                (self.hide_at is not None and now >= self.hide_at)
                or now - self.last_message > self.max_visible_s
            ):
                self.scene.dismiss()
                self.hide_at = None
            if not self.shown:
                previous = time.perf_counter()
                glfw.wait_events_timeout(HIDDEN_WAIT_S)
                continue
            if not self.scene.visible:
                self._hide()
                continue
            current = time.perf_counter()
            self.scene.update(min(current - previous, 0.1))
            previous = current
            if self.card_dirty:
                self._upload_card()
            self.renderer.draw(self.scene)
            glfw.swap_buffers(self.window)
            glfw.poll_events()
            time.sleep(max(0.0, FRAME_S - (time.perf_counter() - current)))


def _read_stdin(inbox: queue.Queue[dict[str, Any] | None]) -> None:
    for raw in sys.stdin.buffer:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict):
            inbox.put(message)
    inbox.put(None)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    first = sys.stdin.buffer.readline()
    config = json.loads(first) if first.strip() else {}
    try:
        overlay = Overlay(config)
    except Exception:
        log.exception("The overlay could not start")
        return EXIT_NO_GRAPHICS
    inbox: queue.Queue[dict[str, Any] | None] = queue.Queue()
    threading.Thread(target=_read_stdin, args=(inbox,), daemon=True).start()
    try:
        overlay.run(inbox)
    finally:
        glfw.terminate()
    return 0
