"""
PC Agent — Phase 1 entry point.

Loop:
    IDLE -> (wake word heard) -> LISTENING -> record utterance ->
    TRANSCRIBING -> agent.handle_utterance() -> RESPONDING (TTS) -> LISTENING

Run with:  python main.py
Run text-only (no mic/wake-word, for testing tools quickly):
           python main.py --text
"""

from __future__ import annotations

import argparse
import sys

from core.config import get_config
from core.logging_setup import get_logger

log = get_logger()


def _import_all_tools() -> None:
    """Every tools/*.py and computer/*.py module registers itself with
    core.tool_registry on import. Importing them here — once, at
    startup — is what populates the registry; nothing else should
    need to import these modules directly."""
    import apps.chatgpt  # noqa: F401
    import apps.powerpoint  # noqa: F401
    import apps.vscode  # noqa: F401
    import apps.word  # noqa: F401
    import browser.browser  # noqa: F401
    import computer.keyboard  # noqa: F401
    import computer.mouse  # noqa: F401
    import computer.windows  # noqa: F401
    # computer.accessibility is imported lazily by vision.screen, not
    # registered directly — it exposes helper functions, not tools.
    import tools.filesystem  # noqa: F401
    import tools.python  # noqa: F401
    import tools.terminal  # noqa: F401
    import vision.screen  # noqa: F401


def run_text_mode() -> None:
    """No microphone, no wake word — type commands directly. Useful for
    developing/testing the planner and tools without the audio stack."""
    from core.agent import Agent
    from core.executor import Executor
    from core.planner import Planner
    from security.confirmation import CliConfirmer

    _import_all_tools()
    cfg = get_config()

    confirmer = CliConfirmer()
    executor = Executor(confirmer, auto_approve_low_risk=cfg.security.auto_approve_low_risk)
    planner = Planner()
    agent = Agent(planner, executor, confirmer, speak_fn=lambda t: print(f"[AGENT] {t}"))
    agent.start_wake()

    print("Text mode. Type a command (or 'quit' to exit).")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() in {"quit", "exit"}:
            break
        reply = agent.handle_utterance(text)
        print(f"[AGENT] {reply}")


def _start_gesture_thread(agent, tts, paused_event) -> None:
    """Spec section 15: gestures map to agent actions. Runs on its own
    thread since the wake-word loop below also blocks on audio reads —
    the two loops are independent producers that both drive the same
    Agent, which is safe here because Agent.handle_utterance runs to
    completion before the next call (no concurrent task execution)."""
    import threading

    from vision.gestures import GestureController

    def on_gesture_action(action: str) -> None:
        log.info(f"Gesture action: {action}")
        if action == "wake":
            agent.start_wake()
            tts.speak("I'm listening.")
        elif action in ("stop", "confirm"):
            # Reuses the same control-word handling as spoken "stop"/
            # "confirm" so there's exactly one place that logic lives.
            reply = agent.handle_utterance(action)
            tts.speak(reply)
        elif action in ("next", "previous", "click"):
            log.info(f"Gesture '{action}' received (no bound action outside an active UI context yet)")

    controller = GestureController(on_action=on_gesture_action, paused=paused_event)
    thread = threading.Thread(target=controller.run, daemon=True, name="gesture-loop")
    thread.start()
    log.info("Gesture recognition thread started")


def run_voice_mode() -> None:
    """Full hands-free loop: wake word -> record -> transcribe -> agent -> speak."""
    import threading
    import time

    import numpy as np
    import sounddevice as sd

    from core.agent import Agent
    from core.executor import Executor
    from core.planner import Planner
    from core.state import AgentState
    from core.status_bus import pop_commands, write_status
    from security.confirmation import CliConfirmer
    from voice.stt import AudioRecorder, SpeechToText, strip_end_phrase
    from voice.tts import build_tts
    from voice.wakeword import WakeWordDetector

    _import_all_tools()
    cfg = get_config()

    log.info("Loading models (this can take a while on first run)...")
    stt = SpeechToText()
    tts = build_tts()
    wake = WakeWordDetector()
    recorder = AudioRecorder(stt=stt)

    confirmer = CliConfirmer()
    executor = Executor(confirmer, auto_approve_low_risk=cfg.security.auto_approve_low_risk)
    planner = Planner()
    agent = Agent(planner, executor, confirmer, speak_fn=tts.speak)

    # Runtime flags the dashboard/tray can flip via core/status_bus.py's
    # command queue — see the "Not covered by ... " note in that module
    # for why this is file-backed IPC rather than a shared object.
    muted = threading.Event()
    gestures_paused = threading.Event()

    if cfg.gestures.enabled:
        _start_gesture_thread(agent, tts, gestures_paused)

    def apply_pending_commands() -> bool:
        """Returns True if a 'stop' command should end the process."""
        for command in pop_commands():
            log.info(f"Dashboard/tray command received: {command}")
            if command == "mute":
                muted.set()
            elif command == "unmute":
                muted.clear()
            elif command == "disable_gestures":
                gestures_paused.set()
            elif command == "enable_gestures":
                gestures_paused.clear()
            elif command == "pause":
                agent.sm.pause()
            elif command == "resume":
                if agent.sm.state.name == "PAUSED":
                    agent.sm.transition(AgentState.LISTENING, force=True)
            elif command in ("stop", "cancel"):
                agent.sm.force_idle()
        return False

    frame_samples = int(cfg.wake_word.sample_rate * cfg.wake_word.frame_ms / 1000)
    log.info(f"Listening for wake word '{cfg.wake_word.phrase}'...")

    last_status_write = 0.0
    status_write_interval_s = 1.0

    with sd.InputStream(
        samplerate=cfg.wake_word.sample_rate,
        channels=1,
        dtype="int16",
        blocksize=frame_samples,
    ) as stream:
        try:
            while True:
                apply_pending_commands()

                now = time.time()
                if now - last_status_write >= status_write_interval_s:
                    write_status(
                        state=agent.sm.state.value,
                        current_task=agent.sm.task.raw_command,
                        current_application=agent.sm.task.current_application,
                        last_action=agent.sm.task.last_action,
                        extra={"muted": muted.is_set(), "gestures_paused": gestures_paused.is_set()},
                    )
                    last_status_write = now

                frame, _ = stream.read(frame_samples)
                if muted.is_set():
                    continue

                if wake.process_frame(frame.flatten()):
                    log.info("Wake word detected")
                    agent.start_wake()
                    tts.speak("I'm listening.")

                    audio = recorder.record_utterance()
                    text = stt.transcribe(audio)
                    if not text:
                        tts.speak("I didn't catch that.")
                        continue

                    text = strip_end_phrase(text, cfg.audio.end_phrase)
                    log.info(f"User said: {text}")
                    reply = agent.handle_utterance(text)
                    tts.speak(reply)
                    wake.reset()
        except KeyboardInterrupt:
            log.info("Shutting down.")
        finally:
            write_status(state="IDLE", current_task=None)


def main() -> None:
    parser = argparse.ArgumentParser(description="PC Agent (Phase 1)")
    parser.add_argument("--text", action="store_true", help="Run in text-only mode (no mic/wake-word).")
    args = parser.parse_args()

    try:
        get_config()
    except FileNotFoundError as e:
        print(f"Config error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.text:
        run_text_mode()
    else:
        run_voice_mode()


if __name__ == "__main__":
    main()
