"""
Local web dashboard (spec section 19).

Deliberately a single-file FastAPI app serving one embedded HTML page
(polling /api/status every second) rather than a separate React/Vite
build. A full SPA build pipeline is real overhead — a second
package.json, a build step, a dev server — for a page whose entire
job is "show me a JSON blob and four buttons." If the dashboard grows
real interactivity later (live logs streaming, drag-and-drop task
reordering), that's the point to reach for React; until then this is
the honest amount of engineering for what the feature needs.

This process is independent of `python main.py` — it only reads/writes
core/status_bus.py's files, never imports voice/vision/computer
modules directly, so the dashboard can crash or restart without
touching the running agent.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from core.config import get_config
from core.status_bus import VALID_COMMANDS, push_command, read_status

app = FastAPI(title="PC Agent Dashboard")

_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>PC Agent Dashboard</title>
<style>
  body { font-family: system-ui, sans-serif; background: #12141a; color: #e8e8e8; margin: 0; padding: 2rem; }
  h1 { font-size: 1.3rem; font-weight: 600; }
  .state { display: inline-block; padding: 0.3rem 0.8rem; border-radius: 999px; font-weight: 600; }
  .state-IDLE { background: #333; }
  .state-LISTENING, .state-WAKE { background: #1f6feb; }
  .state-EXECUTING, .state-PLANNING, .state-OBSERVING, .state-VERIFYING { background: #9a6700; }
  .state-RESPONDING { background: #2ea043; }
  .state-PAUSED { background: #8250df; }
  .state-UNKNOWN { background: #444; }
  .row { margin: 1rem 0; }
  .label { color: #888; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .value { font-size: 1.05rem; }
  button { background: #21262d; color: #e8e8e8; border: 1px solid #30363d; border-radius: 6px;
           padding: 0.5rem 1rem; margin-right: 0.5rem; margin-top: 0.5rem; cursor: pointer; font-size: 0.9rem; }
  button:hover { background: #30363d; }
  .stale { color: #f85149; font-size: 0.8rem; }
</style>
</head>
<body>
  <h1>PC Agent</h1>
  <div class="row"><span id="state" class="state state-UNKNOWN">UNKNOWN</span> <span id="stale" class="stale"></span></div>
  <div class="row"><div class="label">Current task</div><div class="value" id="task">—</div></div>
  <div class="row"><div class="label">Current application</div><div class="value" id="app">—</div></div>
  <div class="row"><div class="label">Last action</div><div class="value" id="action">—</div></div>
  <div class="row">
    <button onclick="cmd('pause')">Pause</button>
    <button onclick="cmd('resume')">Resume</button>
    <button onclick="cmd('cancel')">Cancel task</button>
    <button onclick="cmd('stop')">Stop</button>
    <button onclick="cmd('mute')">Mute mic</button>
    <button onclick="cmd('unmute')">Unmute mic</button>
    <button onclick="cmd('disable_gestures')">Disable gestures</button>
    <button onclick="cmd('enable_gestures')">Enable gestures</button>
  </div>
<script>
async function refresh() {
  try {
    const r = await fetch('/api/status');
    const s = await r.json();
    const el = document.getElementById('state');
    el.textContent = s.state || 'UNKNOWN';
    el.className = 'state state-' + (s.state || 'UNKNOWN');
    document.getElementById('task').textContent = s.current_task || '—';
    document.getElementById('app').textContent = s.current_application || '—';
    document.getElementById('action').textContent = s.last_action || '—';
    const stale = document.getElementById('stale');
    if (s.updated_at && (Date.now()/1000 - s.updated_at) > 10) {
      stale.textContent = '(agent process not responding — is python main.py running?)';
    } else {
      stale.textContent = '';
    }
  } catch (e) { /* dashboard server itself is fine; ignore transient fetch errors */ }
}
async function cmd(name) {
  await fetch('/api/command/' + name, { method: 'POST' });
}
refresh();
setInterval(refresh, 1000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE


@app.get("/api/status")
def api_status() -> dict:
    return read_status()


@app.post("/api/command/{command}")
def api_command(command: str) -> JSONResponse:
    if command not in VALID_COMMANDS:
        return JSONResponse(status_code=400, content={"ok": False, "error": f"Unknown command '{command}'"})
    push_command(command)
    return JSONResponse(content={"ok": True, "command": command})


def run() -> None:
    import uvicorn

    cfg = get_config().dashboard
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning")


if __name__ == "__main__":
    run()
