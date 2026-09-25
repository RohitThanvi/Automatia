# PC Agent — Phase 1

A local, voice-driven desktop agent for Windows. This is **Phase 1** of the
8-phase build plan: wake word + speech-to-text + a local LLM planner (via
Ollama) + a safety-gated tool-execution layer covering files, terminal,
basic app launching, mouse/keyboard, browser, and OCR-based screen reading.

Everything runs locally. No audio, screenshots, or files are sent to any
cloud service.

## What works right now

- Wake word listening (`voice/wakeword.py`)
- Offline speech-to-text via faster-whisper, auto language detection
  (handles Hindi/English mixed speech) (`voice/stt.py`)
- Local LLM planning via Ollama, one tool call at a time, with a
  fast/slow model router for trivial vs. complex commands (`core/planner.py`)
- A hard safety layer: every tool call is classified LOW/MEDIUM/HIGH risk
  and MEDIUM/HIGH always requires you to say/type "confirm" first
  (`security/permissions.py`, `security/confirmation.py`)
- Observe → verify → retry loop around every action, capped at 3 retries
  and 25 steps per task so nothing can loop forever (`core/executor.py`,
  `core/agent.py`)
- Real, working tools: file create/read/write/rename/move/copy/delete,
  shell/PowerShell commands, sandboxed Python execution, app open/close/
  focus/list-windows, mouse/keyboard control, browser open/search,
  screenshot + OCR-based `read_screen`/`find_ui_element`
- Offline TTS via pyttsx3 (Piper supported as a drop-in upgrade)
- SQLite long-term memory + task history

**Phase 2 (done):** `find_ui_element` now tries the Windows UI Automation
tree first (`computer/accessibility.py`) — exact element bounds, control
type, and enabled state straight from the accessibility API, no screenshot
needed — and only falls back to OCR when UIA can't see the element (some
custom-drawn UIs). A new `list_ui_elements` tool lets the agent (or you,
in `--text` mode) dump every named clickable element currently visible,
which is the fastest way to debug "why didn't it find the button".

**Phase 3 (done):** the observe/verify loop is no longer optional — after
`open_application`, the agent automatically confirms a matching window
actually appeared (spec's own example: "if PowerPoint isn't open, detect
this") without needing the LLM to remember to check. Failures are now
categorized (`NOT_FOUND`, `TIMEOUT`, `PERMISSION`, `UNAVAILABLE`, `DENIED`)
in `core/executor.py`, and retries are skipped for categories that won't
self-resolve (a permission error won't fix itself by trying again 200ms
later) — only `NOT_FOUND`/`UNKNOWN` failures burn the retry budget.

**Phase 4 (partial — the flagship feature):** `create_presentation` and
`create_document` (`apps/powerpoint.py`, `apps/word.py`) generate real,
fully-formatted `.pptx`/`.docx` files directly via python-pptx/python-docx
— deterministic, works even without PowerPoint/Word installed, and far
faster than clicking through menus. This is deliberately NOT UI automation:
see the module docstrings for why. VS Code integration
(`apps/vscode.py`) adds project registration by name ("open my VAYU
project") and running commands scoped to a project's folder. Browser
tab-level control and a dedicated ChatGPT-automation module still need
the Playwright bridge and remain future work.

**Phase 5 (done):** `find_ui_element`'s final fallback — when both UIA and
OCR miss, `vision/vision_model.py` sends a screenshot to Gemma 3 (via
Ollama) and asks it to locate the element by description, parsing back
pixel coordinates. Only called on a miss, never polled continuously.

**Phase 6 (done):** gesture recognition via MediaPipe hand landmarks
(`vision/gestures.py`) — open palm (wake), pinch (click), thumbs up
(confirm), closed fist (stop), swipe left/right (previous/next), each
with its own debounce cooldown so a held pose doesn't fire repeatedly.
Off by default (`gestures.enabled: false`); when enabled, `main.py` runs
it on its own thread alongside the wake-word loop.

## What's intentionally NOT built yet (see the phase plan)

- Local web dashboard, system tray (Phase 7)
- PyInstaller packaging / auto-start with Windows (Phase 8)

These are stubbed with clear "not yet available" errors rather than fake
implementations, per the project's engineering rules.

## Try the new features (text mode)

```
> create a presentation about the Indus Valley Civilization with 5 slides
> write a 3-paragraph essay about GaN HEMTs and save it as a Word document
> register the project VAYU at C:\Users\you\Projects\VAYU
> open my VAYU project
> run tests in VAYU
```

The LLM plans and writes the actual content; `create_presentation`/
`create_document` just take that structured content and turn it into a
real file.

## 1. Prerequisites (Windows)

1. **Python 3.11 or 3.12** (64-bit) — https://python.org
2. **Ollama** — https://ollama.com/download, then pull the models:
   ```powershell
   ollama pull qwen3:30b-a3b
   ollama pull qwen2.5:3b
   ```
   `qwen3:30b-a3b` needs a reasonably strong GPU (16GB+ VRAM recommended).
   If your laptop can't run it, edit `config.yaml` and point both
   `llm.model` and `llm.fast_model` at something smaller, e.g. `qwen2.5:7b`
   and `qwen2.5:3b`.
3. **Tesseract OCR** (for `read_screen`/`find_ui_element`) —
   https://github.com/UB-Mannheim/tesseract/wiki — install and make sure
   `tesseract.exe` is on your PATH.
4. **A working microphone.**

## 2. Install

```powershell
cd pc_agent
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

`faster-whisper` will download the Whisper model the first time you run
the agent (a few GB for `large-v3-turbo`). If you have a CUDA GPU it will
use it automatically; otherwise it falls back to CPU (slower).

## 3. Try it without voice first

This skips the microphone/wake-word entirely and lets you type commands
straight to the planner — the fastest way to verify your Ollama setup and
tool layer work before dealing with audio:

```powershell
python main.py --text
```

Try things like:
```
> create a folder called Research
> write a short note to notes.txt saying "hello from the agent"
> open chrome
```

## 4. Run the full hands-free agent

```powershell
python main.py
```

Say the wake phrase, then speak your command. See the note in
`voice/wakeword.py` about the default wake word: the bundled openWakeWord
model listens for **"hey jarvis"**, not literally "start", unless you train
a custom model. Fastest path: set `wake_word.model: "hey_jarvis"` in
`config.yaml` to match what's actually bundled, or train your own model
for "start" using openWakeWord's training notebook.

## 5. Safety

Every action the agent takes is classified LOW / MEDIUM / HIGH risk
(`security/permissions.py`). LOW risk (opening apps, reading/writing files,
typing, clicking) runs automatically. MEDIUM (closing apps, moving/copying
files, running shell commands) and HIGH (deleting anything) **always**
stop and ask you to confirm — this cannot be disabled from a voice command,
only by you editing `security/permissions.py` yourself.

Say "stop", "cancel", or "abort" at any time to immediately return the
agent to idle.

## 6. Running tests

```powershell
pip install pytest
pytest tests/ -v
```

The state machine, permission system, tool registry, filesystem tools,
executor retry/categorization logic, UIA platform guards, PowerPoint/Word
generation, and VS Code project tools are all covered by fast,
deterministic tests that don't need a microphone, GPU, or Ollama running.
(67 tests, all passing as of this build — including gesture classification
with synthetic hand-landmark data and the vision-model fallback's response
parsing.)

## 7. Project layout

See `config.yaml` for every tunable — nothing is hard-coded elsewhere.
Module layout follows the phase plan; each `tools/*.py` and
`computer/*.py` file self-registers its functions with
`core/tool_registry.py` on import (see `main.py:_import_all_tools`).

## What to build next (Phase 7 / 8)

Phase 7 is the local web dashboard (FastAPI + React) and Windows system
tray icon — pure UX, no new agent capability. Phase 8 is packaging
(PyInstaller build, auto-start with Windows) and a performance pass
(persistent model processes, caching UI state between calls). Both are
lower-risk, mechanical work compared to Phases 1-6, which is why they're
last — everything the agent can actually *do* is now in place.
