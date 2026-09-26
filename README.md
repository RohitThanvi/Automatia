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

**Phase 7 (done):** a local dashboard (`dashboard/server.py`, FastAPI —
single embedded HTML page, no separate build step, see the module
docstring for why) shows live agent state and lets you Pause/Resume/
Cancel/Stop/Mute/toggle gestures from a browser. It talks to the running
`python main.py` process through `core/status_bus.py` — two small JSON
files (`data/status.json`, `data/commands.json`), written atomically, so
the dashboard and agent are separate processes that can't take each other
down. `tray.py` adds a Windows system tray icon (via pystray) to
start/stop the agent, open the dashboard, and toggle "start with Windows"
via a Startup-folder shortcut — no admin rights needed.

**Phase 8 (partial):** `build/pyinstaller.spec` packages the agent, tray,
and dashboard into a `PC_Agent/` folder of three .exe's sharing one set of
dependencies (`--onedir`, not `--onefile` — see the spec's comment for
why). **This spec is written but untested** — I can't run PyInstaller
against Windows-only dependencies (pywinauto, pystray's win32 backend)
from this sandbox, so treat it as a strong starting point, not a
guaranteed-working build; you'll likely need to iterate on hidden-imports
once you actually run it. Performance-wise, the architecture already does
what Phase 8 asks for: models load once at startup and stay resident
(`SpeechToText`/`Planner`/`TextToSpeech` are constructed once in
`run_voice_mode`, not per-utterance), the wake-word loop never touches the
LLM, and the fast/slow model router avoids the 30B model for trivial
commands.

## Running the dashboard and tray

```powershell
# Terminal 1 — the agent itself
python main.py

# Terminal 2 — the dashboard (optional, separate process)
python -m dashboard.server
# then open http://127.0.0.1:8765 in a browser

# OR, instead of both of the above: the tray icon manages both for you
python tray.py
```

## What's intentionally NOT built yet

- A trained "start" wake-word model (see the wake-word section above)
- Building/testing the actual .exe from `build/pyinstaller.spec`
- UPX compression, code signing, or an installer (.msi/.exe) wrapper

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

## Optional: end-phrase mode (say "over" to stop, instead of pausing)

By default the agent ends your utterance after `silence_timeout_ms` of
quiet — good for short commands, but it'll cut you off mid-thought if
you're dictating something long (an essay, a multi-step instruction) and
pause naturally. Set an end phrase in `config.yaml` to change that:

```yaml
audio:
  end_phrase: "over"          # or "that's all", "done talking", etc.
  end_phrase_recheck_ms: 1500 # how often to re-check during a pause
```

With this set, an ordinary pause no longer ends the recording — only
saying the phrase (or hitting `max_utterance_seconds`) does. There's no
way to detect a spoken phrase without transcribing, so this works by
re-transcribing what's been said so far every `end_phrase_recheck_ms` of
continued silence, checking only whether it *ends with* the phrase — not
a continuous stream, just a check on each pause. The phrase itself is
stripped from the final text before it reaches the planner, so saying
"write a haiku about rain, over" sends "write a haiku about rain".

## 1. Prerequisites (Windows)

1. **Python 3.11 or 3.12** (64-bit) — https://python.org
2. **Ollama** — https://ollama.com/download, then pull the models
   configured in `config.yaml`:
   ```powershell
   ollama pull qwen2.5:7b
   ollama pull qwen2.5:3b
   ollama pull gemma3:27b
   ```
   Adjust `llm.model`/`llm.fast_model`/`vision.model` in `config.yaml` to
   match whatever you actually pull — those three are just what this
   config currently points at.
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
(99 tests, all passing as of this build — including gesture classification
with synthetic hand-landmark data, the vision-model fallback's response
parsing, the status bus/dashboard API, and the tray's process-management
logic.)

## 7. Project layout

See `config.yaml` for every tunable — nothing is hard-coded elsewhere.
Module layout follows the phase plan; each `tools/*.py` and
`computer/*.py` file self-registers its functions with
`core/tool_registry.py` on import (see `main.py:_import_all_tools`).

## What to build next

All 8 phases from the original plan now have a real implementation. What's
left is hardening, not new capability:
- Iterate on `build/pyinstaller.spec` against a real Windows build (it's
  untested, see above)
- Train or source a proper "start" wake-word model
- Broaden the ChatGPT selectors (`apps/chatgpt.py`) if/when the site's DOM
  changes them
- More per-application recovery strategies as you hit real failures in use
