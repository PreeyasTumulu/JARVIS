"""The voice loop: push-to-talk or wake word, speech to text, the agent, and spoken replies.

Dictation shares the microphone and Whisper but not the agent: its hotkey records like
push-to-talk, and the text goes to the focused app instead of to the model (ADR-054).

Everything runs on the asyncio loop. Hotkeys arrive from their own thread through
`loop.call_soon_threadsafe(session.on_hotkey, ...)`; blocking model calls (Whisper, openWakeWord,
Silero) run in worker threads. The microphone has a single reader, `_frame_loop`, which routes
each 80 ms frame to the push-to-talk buffer, the endpointer, or the wake word detector.
"""

from __future__ import annotations

import asyncio
import logging
import statistics
import time
from collections.abc import Coroutine
from enum import StrEnum
from typing import Any, Protocol

import numpy as np

from jarvis.config import Settings
from jarvis.core.agent import Agent, TurnStatus
from jarvis.core.events import EventBus, TranscriptHeard, VoiceStateChanged
from jarvis.voice.audio import FRAME_MS, Audio
from jarvis.voice.dictation import DictationError
from jarvis.voice.endpoint import Endpoint, Endpointer
from jarvis.voice.phrases import is_stop_command
from jarvis.voice.stt import Transcript
from jarvis.voice.tts.base import TTSEngine

log = logging.getLogger(__name__)

WAKE_COOLDOWN_S = 1.5  # ignore the wake word right after it fired
ECHO_TAIL_S = 0.4  # ignore the wake word right after Jarvis stops speaking
MIC_STALL_S = 3.0  # an open microphone that sends nothing this long has died; reopen it
MIC_RETRY_S = 5.0  # wait between attempts while the microphone cannot be reopened


class VoiceState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    AWAITING_ANSWER = "awaiting_answer"
    MUTED = "muted"  # the microphone is off (tray): no push-to-talk, no wake word


RESTING = (VoiceState.IDLE, VoiceState.MUTED)  # nothing going on; a reminder may speak


class Capture(StrEnum):
    NONE = "none"
    PUSH_TO_TALK = "push_to_talk"
    ENDPOINT = "endpoint"  # after the wake word: record until the speaker pauses
    DICTATION = "dictation"  # like push-to-talk, but the text is typed into the focused app


class AudioIn(Protocol):
    @property
    def active(self) -> bool: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def read(self) -> Audio | None: ...
    async def restart(self) -> None: ...
    def drain(self) -> None: ...


class SpeechToText(Protocol):
    def load(self) -> None: ...
    def transcribe(self, audio: Audio, *, dictation: bool = False) -> Transcript: ...


class Dictation(Protocol):
    def insert(self, text: str) -> str: ...  # blocking; "typed", "pasted", or "" for nothing


class WakeWord(Protocol):
    def load(self) -> None: ...
    def score(self, frame: Audio) -> float: ...
    def reset(self) -> None: ...


class VoiceActivity(Protocol):
    def load(self) -> None: ...
    def probability(self, frame: Audio) -> float: ...


class Cues(Protocol):
    async def listening(self) -> None: ...
    async def cancelled(self) -> None: ...


class VoiceSession:
    def __init__(
        self,
        *,
        agent: Agent,
        bus: EventBus,
        settings: Settings,
        mic: AudioIn,
        stt: SpeechToText,
        tts: TTSEngine,
        cues: Cues,
        wake: WakeWord | None = None,
        vad: VoiceActivity | None = None,
        dictation: Dictation | None = None,
    ) -> None:
        if (wake is None) != (vad is None):
            raise ValueError("Wake word mode needs both a wake word detector and a VAD")
        self._agent = agent
        self._bus = bus
        self._cfg = settings.voice
        self._mic = mic
        self._stt = stt
        self._tts = tts
        self._cues = cues
        self._wake = wake
        self._vad = vad
        self._dictation = dictation
        self._state = VoiceState.IDLE
        self._muted = False
        self._idle = asyncio.Event()
        self._idle.set()
        self._capture = Capture.NONE
        self._buffer: list[Audio] = []
        self._endpointer: Endpointer | None = None
        self._frame_task: asyncio.Task[None] | None = None
        self._turn_task: asyncio.Task[None] | None = None
        self._pending_answer: asyncio.Future[str] | None = None
        self._ptt_lock = asyncio.Lock()
        self._wake_quiet_until = 0.0
        self._speech_end = 0.0
        self._tasks: set[asyncio.Task[Any]] = set()
        self.heard_to_action_ms: list[int] = []

    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def wake_enabled(self) -> bool:
        return self._wake is not None

    @property
    def muted(self) -> bool:
        return self._muted

    async def set_muted(self, muted: bool) -> None:
        """Turn the microphone off or on (the tray's Microphone item). Speaking still works."""
        if muted == self._muted:
            return
        self._muted = muted
        if muted:
            if self._capture is not Capture.NONE:
                self._end_capture()
            await self._close_mic()
            await self._set_state(VoiceState.MUTED, "microphone off")
        else:
            if self.wake_enabled:
                await self._open_mic()
            await self._set_state(VoiceState.IDLE)

    # Lifecycle

    async def load(self) -> None:
        """Load every model up front so the first command is not slow. Blocking work in threads."""
        loaders = [self._stt.load]
        for component in (self._tts, self._wake, self._vad):
            loader = getattr(component, "load", None)
            if callable(loader):
                loaders.append(loader)
        for loader in loaders:
            await asyncio.to_thread(loader)

    async def run(self) -> None:
        """Run until cancelled. In wake word mode the microphone stays open."""
        try:
            if self.wake_enabled:
                await self._open_mic()
            await self._set_state(VoiceState.IDLE)
            await asyncio.Event().wait()
        finally:
            await self.close()

    async def close(self) -> None:
        self._agent.cancel()
        tasks = [t for t in (*self._tasks, self._frame_task) if t is not None and not t.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self._tts.stop()
        await self._mic.stop()

    def latency_summary(self) -> str | None:
        if not self.heard_to_action_ms:
            return None
        values = self.heard_to_action_ms
        return (
            f"{len(values)} voice command(s), median {statistics.median(values) / 1000:.1f}s "
            "from end of speech to the first action"
        )

    # Inputs

    def on_hotkey(self, name: str, phase: str) -> None:
        """Called on the event loop thread (via call_soon_threadsafe)."""
        if name == "ptt":
            self._spawn(self._ptt_down() if phase == "down" else self._ptt_up())
        elif name == "dictate":
            self._spawn(self._dictate_down() if phase == "down" else self._dictate_up())
        elif name == "stop" and phase == "down":
            self._spawn(self.stop())

    async def stop(self) -> None:
        """Stop everything: the running command, speech, listening, and any pending question."""
        self._agent.cancel()
        await self._tts.stop()
        if self._capture is not Capture.NONE:
            self._end_capture()
        if self._pending_answer is not None and not self._pending_answer.done():
            self._pending_answer.set_result("")
        await self._cues.cancelled()
        await self._set_state(self._rest_state, "stopped")

    async def announce(self, text: str) -> None:
        """Say something Jarvis brings up on its own (a reminder) without talking over anyone."""
        while self._state not in RESTING:
            await self._idle.wait()
        await self._speak(text)

    async def ask_and_listen(self, prompt: str) -> str:
        """Speak a question and return the next thing the user says (used for confirmations).

        The question may belong to a command typed in the web UI, and the page may answer
        first; either way the session goes back to the state it was in before asking.
        """
        if self._muted:
            # Voice drops out of the race; the page or the terminal answers instead.
            raise RuntimeError("The microphone is off.")
        before = self._state
        resume = before if before in (VoiceState.IDLE, VoiceState.THINKING) else VoiceState.THINKING
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending_answer = future
        try:
            await self._speak(prompt)
            if not future.done():
                detail = (
                    "say it after the beep" if self.wake_enabled else "hold the hotkey to answer"
                )
                await self._set_state(VoiceState.AWAITING_ANSWER, detail)
                if self.wake_enabled and self._capture is Capture.NONE:
                    await self._start_listening()
            return await future
        finally:
            answered_here = future.done() and not future.cancelled()
            if self._pending_answer is future:
                self._pending_answer = None
            if not future.done():
                future.cancel()
            if not answered_here and self._capture is Capture.ENDPOINT:
                self._end_capture()  # another channel answered: stop recording the answer
            if self._state is not resume and self._state is not VoiceState.SPEAKING:
                await self._set_state(resume)

    # Push-to-talk

    async def _ptt_down(self) -> None:
        if self._muted:
            return
        async with self._ptt_lock:
            await self._interrupt()
            await self._open_mic()
            await self._cues.listening()
            self._begin_capture(Capture.PUSH_TO_TALK)
            await self._set_state(VoiceState.LISTENING, "release the hotkey when done")

    async def _ptt_up(self) -> None:
        async with self._ptt_lock:
            if self._capture is not Capture.PUSH_TO_TALK:
                return
            await asyncio.sleep(FRAME_MS / 1000)  # let the last frame arrive
            audio = self._end_capture()
            self._speech_end = time.perf_counter()
            if not self.wake_enabled:
                await self._close_mic()
        self._spawn(self._process(audio))

    # Dictation

    async def _dictate_down(self) -> None:
        if self._muted or self._dictation is None:
            return
        async with self._ptt_lock:
            if self._pending_answer is not None and not self._pending_answer.done():
                await self._cues.cancelled()  # a question is waiting: answer it, not dictate
                return
            if self._state is VoiceState.SPEAKING:
                await self._tts.stop()
            if self._capture is not Capture.NONE:
                self._end_capture()
            await self._open_mic()
            await self._cues.listening()
            self._begin_capture(Capture.DICTATION)
            await self._set_state(VoiceState.LISTENING, "dictating: release to type")

    async def _dictate_up(self) -> None:
        async with self._ptt_lock:
            if self._capture is not Capture.DICTATION:
                return
            await asyncio.sleep(FRAME_MS / 1000)  # let the last frame arrive
            audio = self._end_capture()
            if not self.wake_enabled:
                await self._close_mic()
        self._spawn(self._dictate(audio))

    async def _dictate(self, audio: Audio) -> None:
        """Transcribe and insert. The agent never sees dictated text, and nothing is spoken
        unless the text could not be inserted."""
        assert self._dictation is not None
        await self._set_state(VoiceState.TRANSCRIBING, "dictation")
        transcript = await asyncio.to_thread(self._stt.transcribe, audio, dictation=True)
        text = transcript.text
        if not text or is_stop_command(text):
            await self._nothing_heard()
            return
        try:
            how = await asyncio.to_thread(self._dictation.insert, text)
        except DictationError as exc:
            await self._set_state(self._rest_state)
            await self._speak(str(exc))
            return
        except Exception:
            log.exception("Dictation failed")
            await self._set_state(self._rest_state)
            await self._speak("I couldn't type that. The details are in the log file.")
            return
        log.info(
            "Dictation: %d characters %s in %d ms", len(text), how or "dropped", transcript.stt_ms
        )
        if self._state is VoiceState.TRANSCRIBING:
            await self._set_state(self._rest_state)

    # Microphone routing

    async def _open_mic(self) -> None:
        if not self._mic.active:
            await self._mic.start()
        if self._frame_task is None or self._frame_task.done():
            self._frame_task = asyncio.create_task(self._frame_loop(), name="voice-frames")

    async def _close_mic(self) -> None:
        await self._mic.stop()

    async def _frame_loop(self) -> None:
        while True:
            try:
                frame = await asyncio.wait_for(self._mic.read(), timeout=MIC_STALL_S)
            except TimeoutError:
                if self._mic.active:
                    await self._recover_mic()
                continue
            if frame is None:
                if self._mic.active:
                    continue  # a stale end marker from before the microphone was reopened
                return
            try:
                await self._route(frame)
            except Exception:
                log.exception("Voice frame handling failed")

    async def _recover_mic(self) -> None:
        """The stream went quiet without closing (sleep, a device change): open it again."""
        log.warning("The microphone sent no audio for %.0fs; reopening it", MIC_STALL_S)
        if self._capture is not Capture.NONE:
            self._end_capture()
            await self._set_state(self._rest_state, "microphone reconnected")
        try:
            await self._mic.restart()
        except Exception as exc:
            log.warning("Could not reopen the microphone (%s); trying again shortly", exc)
            await asyncio.sleep(MIC_RETRY_S)
        else:
            log.info("Microphone reopened")

    async def _route(self, frame: Audio) -> None:
        if self._capture in (Capture.PUSH_TO_TALK, Capture.DICTATION):
            self._buffer.append(frame)
        elif self._capture is Capture.ENDPOINT:
            await self._feed_endpointer(frame)
        elif self._wake is not None and self._wake_armed():
            score = await asyncio.to_thread(self._wake.score, frame)
            if score >= self._cfg.wake_threshold:
                log.info("Wake word detected (%.2f)", score)
                self._wake.reset()
                self._wake_quiet_until = time.monotonic() + WAKE_COOLDOWN_S
                await self._interrupt()
                await self._start_listening()

    def _wake_armed(self) -> bool:
        listening_states = (VoiceState.IDLE, VoiceState.THINKING)
        return self._state in listening_states and time.monotonic() >= self._wake_quiet_until

    async def _start_listening(self) -> None:
        await self._cues.listening()
        self._mic.drain()  # drop audio recorded while the cue played
        self._endpointer = Endpointer(
            frame_ms=FRAME_MS,
            threshold=self._cfg.vad_threshold,
            end_silence_ms=self._cfg.end_silence_ms,
            max_ms=int(self._cfg.max_utterance_s * 1000),
            no_speech_ms=int(self._cfg.no_speech_timeout_s * 1000),
        )
        self._begin_capture(Capture.ENDPOINT)
        await self._set_state(VoiceState.LISTENING, "speak now")

    async def _feed_endpointer(self, frame: Audio) -> None:
        assert self._vad is not None
        assert self._endpointer is not None
        self._buffer.append(frame)
        probability = await asyncio.to_thread(self._vad.probability, frame)
        verdict = self._endpointer.feed(probability)
        if verdict is Endpoint.CONTINUE:
            return
        audio = self._end_capture()
        self._speech_end = time.perf_counter()
        if verdict in (Endpoint.DONE, Endpoint.TOO_LONG):
            self._spawn(self._process(audio))
        elif self._pending_answer is not None and not self._pending_answer.done():
            self._pending_answer.set_result("")  # silence after a question counts as no
        else:
            await self._nothing_heard()

    def _begin_capture(self, mode: Capture) -> None:
        self._buffer = []
        self._capture = mode

    def _end_capture(self) -> Audio:
        frames, self._buffer = self._buffer, []
        self._capture = Capture.NONE
        self._endpointer = None
        return np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)

    # Understanding and acting

    async def _process(self, audio: Audio) -> None:
        await self._set_state(VoiceState.TRANSCRIBING)
        transcript = await asyncio.to_thread(self._stt.transcribe, audio)
        if transcript.text:
            await self._bus.publish(
                TranscriptHeard(transcript.text, transcript.audio_ms, transcript.stt_ms)
            )
        await self._handle(transcript)

    async def _handle(self, transcript: Transcript) -> None:
        text = transcript.text
        answering = self._pending_answer is not None and not self._pending_answer.done()
        if not text:
            if answering:
                await self._set_state(VoiceState.AWAITING_ANSWER, "I didn't catch that")
                if self.wake_enabled:
                    await self._start_listening()
            else:
                await self._nothing_heard()
            return
        if is_stop_command(text):
            await self.stop()
            return
        if answering:
            assert self._pending_answer is not None
            self._pending_answer.set_result(text)
            return
        await self._finish_previous_turn()
        self._turn_task = self._spawn(self._run_turn(text, transcript))

    async def _run_turn(self, text: str, transcript: Transcript) -> None:
        await self._set_state(VoiceState.THINKING)
        pre_turn_ms = int((time.perf_counter() - self._speech_end) * 1000)
        timings = {
            "audio_ms": transcript.audio_ms,
            "stt_ms": transcript.stt_ms,
            "pre_turn_ms": pre_turn_ms,
        }
        result = await self._agent.run_turn(text, source="voice", timings=timings)
        if result.status is not TurnStatus.CANCELLED:
            first_action = result.timings.get("first_tool_ms", result.timings.get("turn_ms", 0))
            self.heard_to_action_ms.append(pre_turn_ms + first_action)
            if result.text:
                await self._speak(result.text)
        if self._state in (VoiceState.THINKING, VoiceState.SPEAKING):
            await self._set_state(self._rest_state)

    async def _finish_previous_turn(self) -> None:
        task = self._turn_task
        if task is not None and not task.done():
            self._agent.cancel()
            await self._tts.stop()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=3)
            except (TimeoutError, asyncio.CancelledError):
                task.cancel()

    async def _interrupt(self) -> None:
        """New input arrived: stop talking, and drop the running command unless it is an answer."""
        if self._state is VoiceState.SPEAKING:
            await self._tts.stop()
        answering = self._pending_answer is not None and not self._pending_answer.done()
        if self._agent.busy and not answering:
            self._agent.cancel()

    async def _speak(self, text: str) -> None:
        previous = self._state
        await self._set_state(VoiceState.SPEAKING)
        try:
            await self._tts.speak(text)
        except asyncio.CancelledError:
            await self._tts.stop()
            raise
        except Exception:
            log.exception("Speech output failed")
        finally:
            self._wake_quiet_until = max(self._wake_quiet_until, time.monotonic() + ECHO_TAIL_S)
            if self._wake is not None:
                self._wake.reset()
            if self._state is VoiceState.SPEAKING and previous is not VoiceState.SPEAKING:
                await self._set_state(previous)

    @property
    def _rest_state(self) -> VoiceState:
        return VoiceState.MUTED if self._muted else VoiceState.IDLE

    async def _nothing_heard(self) -> None:
        await self._cues.cancelled()
        await self._set_state(VoiceState.IDLE, "nothing heard")

    # Helpers

    async def _set_state(self, state: VoiceState, detail: str = "") -> None:
        self._state = state
        if state in RESTING:
            self._idle.set()
        else:
            self._idle.clear()
        await self._bus.publish(VoiceStateChanged(state=state, detail=detail))

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("Voice task failed", exc_info=task.exception())
