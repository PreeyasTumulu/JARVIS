"""The overlay's animation state: what each voice state looks like, eased over time. No graphics."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

BARS = 32
BAR_STEP_S = 0.05
HIDDEN_BELOW = 0.004
LONG_AFTER_BURST = 10.0

# Two colours per state. The page's reactor.js has the same table.
PALETTE: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    "listening": ((0.20, 0.85, 1.00), (0.08, 0.32, 1.00)),
    "transcribing": ((0.45, 0.95, 1.00), (0.10, 0.45, 1.00)),
    "thinking": ((0.66, 0.42, 1.00), (0.18, 0.46, 1.00)),
    "speaking": ((1.00, 0.76, 0.28), (0.18, 0.72, 1.00)),
    "awaiting_answer": ((1.00, 0.56, 0.16), (1.00, 0.26, 0.12)),
}
TAKEOVER_STATES = ("listening", "transcribing", "awaiting_answer")


@dataclass
class Targets:
    dim: float = 0.0
    edge: float = 0.0
    core: float = 0.0
    core_y: float = 0.0
    core_size: float = 0.25
    sweep: float = 0.0


def targets_for(state: str, *, mode: str, dim: float) -> Targets:
    """Full screen while you speak; once Jarvis works, an edge glow and a small core (ADR-070)."""
    big = state in TAKEOVER_STATES and mode == "takeover"
    return Targets(
        dim=dim if big else 0.0,
        edge=1.0 if big else 0.55,
        core=1.0,
        core_y=0.085 if big else -0.235,
        core_size=0.2 if big else 0.07,
        sweep=1.0 if state == "thinking" else 0.0,
    )


def _ease(value: float, target: float, dt: float, rate: float) -> float:
    return target + (value - target) * math.exp(-rate * dt)


@dataclass
class Scene:
    mode: str = "takeover"
    max_dim: float = 0.72
    calm: float = 0.0
    state: str = "idle"
    showing: bool = False
    time: float = 0.0
    burst: float = LONG_AFTER_BURST
    dim: float = 0.0
    edge: float = 0.0
    core: float = 0.0
    core_y: float = 0.085
    core_size: float = 0.2
    sweep: float = 0.0
    level: float = 0.0
    text_alpha: float = 0.0
    color_a: list[float] = field(default_factory=lambda: list(PALETTE["listening"][0]))
    color_b: list[float] = field(default_factory=lambda: list(PALETTE["listening"][1]))
    bars: list[float] = field(default_factory=lambda: [0.0] * BARS)
    _heard: float = 0.0
    _bar_clock: float = 0.0
    _targets: Targets = field(default_factory=Targets)

    def wake(self) -> None:
        self.burst = 0.0
        self.showing = True
        big = self.mode == "takeover"
        self.core_y = 0.085 if big else -0.235
        self.core_size = 0.2 if big else 0.07
        self.bars = [0.0] * BARS

    def set_state(self, state: str) -> None:
        self.state = state
        self._targets = targets_for(state, mode=self.mode, dim=self.max_dim)

    def set_level(self, level: float) -> None:
        self._heard = max(0.0, min(level, 1.0))

    def dismiss(self) -> None:
        self.showing = False
        self._targets = Targets(core_y=self.core_y, core_size=self.core_size)

    @property
    def visible(self) -> bool:
        """False once everything has faded, so the window can hide and stop drawing."""
        return self.showing or max(self.dim, self.edge, self.core, self.text_alpha) > HIDDEN_BELOW

    def update(self, dt: float) -> None:
        self.time += dt
        self.burst = min(self.burst + dt, LONG_AFTER_BURST)
        target = self._targets
        self.dim = _ease(self.dim, target.dim, dt, 5.0)
        self.edge = _ease(self.edge, target.edge, dt, 5.0)
        self.core = _ease(self.core, target.core, dt, 6.0)
        self.core_y = _ease(self.core_y, target.core_y, dt, 3.6)
        self.core_size = _ease(self.core_size, target.core_size, dt, 3.6)
        self.sweep = _ease(self.sweep, target.sweep, dt, 4.0)
        self.text_alpha = _ease(self.text_alpha, 1.0 if self.showing else 0.0, dt, 9.0)
        self.level = _ease(self.level, self._voice(), dt, 16.0)
        colors = PALETTE.get(self.state)
        if colors is not None:
            for now, goal in ((self.color_a, colors[0]), (self.color_b, colors[1])):
                for index in range(3):
                    now[index] = _ease(now[index], goal[index], dt, 4.5)
        self._bar_clock += dt
        while self._bar_clock >= BAR_STEP_S:
            self._bar_clock -= BAR_STEP_S
            self.bars = [min(1.0, self.level * 1.15), *self.bars[:-1]]

    def _voice(self) -> float:
        """Your real level while recording. Jarvis's own speech is not measured, so it gets a
        made-up rhythm, and the quiet states rest."""
        if self.state == "listening":
            return self._heard
        if self.state == "speaking":
            t = self.time
            return 0.32 + 0.22 * math.sin(t * 9.1) * math.sin(t * 3.7) + 0.14 * math.sin(t * 17.3)
        if self.state == "thinking":
            return 0.1 + 0.06 * math.sin(self.time * 3.0)
        return 0.0
