"""
xmrig_dashboard.py — XMRig Dashboard
Textual TUI + Flask web mirror on http://127.0.0.1:4727

Usage:
    python xmrig_dashboard.py

Keybinds:
    Q  Quit          R  Restart miner
    P  Pause/Resume  E  Edit config
    W  Toggle web dashboard (http://127.0.0.1:4727)

Requirements:
    pip install textual psutil requests flask
"""

import json
import os
import subprocess
import sys
import threading
import warnings
warnings.filterwarnings('ignore', category=SyntaxWarning)

import psutil
import requests
from flask import Flask, jsonify, render_template_string
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button, Digits, Footer, Header, Input,
    Label, ProgressBar, Static,
)


# ── Constants ────────────────────────────────────────────────────────────────

DASH_CONFIG   = "dash_config.json"
API_ENDPOINTS = ["http://127.0.0.1:16000/1/summary", "http://localhost:16000/1/summary"]
POOL_API_BASE = "https://api.moneroocean.stream/miner/"
PRICE_API     = "https://api.coingecko.com/api/v3/simple/price?ids=monero&vs_currencies="
WEB_PORT      = 4727

ISOMETRIC_LOGO = (
    "[#ff6600]   _  __ __  _______  _      [/]\n"
    "[#ff6600]  | |/ //  |/  / __ \\(_)___ _[/]\n"
    "[#ff6600]  |   // /|_/ / /_/ / / __ `/[/]\n"
    "[#ffffff] /   |/ /  / / _, _/ / /_/ / [/]\n"
    "[#ffffff]/_/|_/_/  /_/_/ |_/_/\\__, /  [/]\n"
    "[#666666]                    /____/    [/]\n"
    "[bold #ff6600]         D A S H B O A R D        [/]"
)

# ── Shared state (written by TUI, read by Flask) ─────────────────────────────

_state: dict = {
    "cpu": "0%",
    "temp": "N/A",
    "status": "STARTING",
    "hashrate": 0.0,
    "history": [],
    "algo": "???",
    "shares": 0,
    "target_shares": 200,
    "threads": [],
    "pending_xmr": 0.0,
    "paid_xmr": 0.0,
    "pending_fiat": 0.0,
    "paid_fiat": 0.0,
    "currency": "USD",
    "xmr_price": 0.0,
    "paused": False,
    "web_active": False,
    "pool": "—",
    "uptime": 0,
    "ping": 0,
}
_state_lock = threading.Lock()


def update_state(**kwargs):
    with _state_lock:
        _state.update(kwargs)


def get_state() -> dict:
    with _state_lock:
        return dict(_state)


# ── Config helpers ───────────────────────────────────────────────────────────

def load_dash_config() -> dict | None:
    if not os.path.exists(DASH_CONFIG):
        return None
    with open(DASH_CONFIG, "r") as f:
        return json.load(f)


def save_dash_config(cfg: dict) -> None:
    with open(DASH_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)


# ── Flask web server ─────────────────────────────────────────────────────────

_flask_thread: threading.Thread | None = None
_flask_app = Flask(__name__)

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>XMRig Dashboard</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg:      #0b0e14;
    --bg2:     #10141e;
    --border:  #1c202a;
    --orange:  #ff6600;
    --blue:    #7aa2f7;
    --green:   #9ece6a;
    --teal:    #73daca;
    --yellow:  #e0af68;
    --muted:   #565f89;
    --text:    #acb0d0;
    --white:   #cdcecf;
  }
  body {
    background: var(--bg);
    color: var(--white);
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    min-height: 100vh;
    padding: 16px;
  }
  #banner {
    background: var(--orange);
    color: var(--bg);
    font-weight: 700;
    text-align: center;
    padding: 4px;
    margin-bottom: 12px;
    border-radius: 3px;
    font-size: 11px;
    letter-spacing: 1px;
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr 1.3fr;
    gap: 16px;
    max-width: 1200px;
    margin: 0 auto;
  }
  .section-label {
    color: var(--muted);
    font-weight: 700;
    border-bottom: 1px solid var(--border);
    padding-bottom: 4px;
    margin: 14px 0 8px;
    font-size: 11px;
    letter-spacing: 1px;
  }
  .stat-row {
    display: flex;
    align-items: center;
    margin-bottom: 4px;
  }
  .stat-label { color: var(--blue); width: 110px; flex-shrink: 0; }
  .stat-value { color: var(--text); font-weight: 700; }
  .status-running { color: var(--green); }
  .status-paused  { color: var(--yellow); }
  .status-offline { color: #f7768e; }
  #hashrate-big {
    color: var(--green);
    font-size: 48px;
    font-weight: 700;
    margin: 8px 0 4px;
    letter-spacing: 3px;
    transition: color 0.3s ease;
  }
  @keyframes flash-update {
    0%   { opacity: 1; }
    20%  { opacity: 0.4; }
    100% { opacity: 1; }
  }
  .flash { animation: flash-update 0.4s ease; }
  .stat-value { color: var(--text); font-weight: 700; transition: color 0.3s; }
  #hashrate-unit { color: var(--muted); font-size: 12px; }
  #spark-canvas {
    width: 100%;
    height: 80px;
    display: block;
    margin: 6px 0;
  }
  .payout-block {
    color: var(--yellow);
    line-height: 1.8;
    margin-top: 4px;
  }
  .payout-fiat { color: var(--green); }
  .engine-box {
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 10px;
    font-size: 12px;
    color: var(--text);
    min-height: 180px;
  }
  .engine-algo { color: #7dcfff; font-weight: 700; margin-bottom: 6px; }
  .thread-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 2px 12px;
  }
  .thread-row { color: var(--text); }
  .thread-id  { color: var(--muted); }
  .progress-wrap { margin-top: 8px; }
  .progress-bar-bg {
    background: var(--border);
    border-radius: 3px;
    height: 8px;
    width: 100%;
    margin-top: 6px;
  }
  .progress-bar-fill {
    background: var(--teal);
    height: 8px;
    border-radius: 3px;
    transition: width 0.5s ease;
  }
  #share-label { color: var(--text); font-size: 12px; margin-bottom: 4px; }
  .logo {
    font-size: 10px;
    line-height: 1.3;
    color: var(--orange);
    text-align: center;
    margin-bottom: 8px;
    white-space: pre;
    overflow: hidden;
  }
  .conn-row { color: var(--muted); font-size: 11px; margin-top: 4px; }
  .conn-val  { color: var(--text); }
</style>
</head>
<body>
<div id="banner">⚡ XMRIG ENGINE MANAGER &nbsp;·&nbsp; Auto-refreshes every 2s</div>
<div class="grid">

  <!-- LEFT PANE -->
  <div>
    <div class="logo"><pre id="ascii-logo" style="color:#ff6600;font-size:11px;line-height:1.4;text-align:center;font-family:'JetBrains Mono',monospace;white-space:pre;">   _  __ __  _______  _
  | |/ //  |/  / __ \(_)___ _
  |   // /|_/ / /_/ / / __ `/
 /   |/ /  / / _, _/ / /_/ /
/_/|_/_/  /_/_/ |_/_/\__, /
                    /____/
      D A S H B O A R D</pre>
</div>

    <div class="section-label">SYSTEM STATUS</div>
    <div class="stat-row">
      <span class="stat-label">CPU Util:</span>
      <span class="stat-value" id="cpu">—</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">CPU Temp:</span>
      <span class="stat-value" id="temp">—</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">Miner:</span>
      <span class="stat-value" id="status">—</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">Pool:</span>
      <span class="stat-value" id="pool" style="color:var(--muted);font-size:11px">—</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">Uptime:</span>
      <span class="stat-value" id="uptime">—</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">Ping:</span>
      <span class="stat-value" id="ping">—</span>
    </div>

    <div class="section-label">HASHRATE TREND</div>
    <div id="hashrate-big">0.0</div>
    <span id="hashrate-unit">H/s</span>
    <canvas id="spark-canvas"></canvas>

    <div class="section-label" id="payout-label">POOL PAYOUTS</div>
    <div class="payout-block" id="payouts">Syncing…</div>
  </div>

  <!-- RIGHT PANE -->
  <div>
    <div class="section-label">LIVE ENGINE</div>
    <div class="engine-box">
      <div class="engine-algo" id="algo">Algo: —</div>
      <div class="thread-grid" id="threads"></div>
    </div>

    <div class="section-label">SESSION PROGRESS</div>
    <div id="share-label">Shares: 0 / 200</div>
    <div class="progress-wrap">
      <div class="progress-bar-bg">
        <div class="progress-bar-fill" id="progress-fill" style="width:0%"></div>
      </div>
    </div>
  </div>

</div>

<script>
const history = [];

function fmt(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function drawSpark(canvas, data) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.offsetWidth;
  const h = canvas.height = canvas.offsetHeight;
  ctx.clearRect(0, 0, w, h);
  if (data.length < 2) return;
  const max = Math.max(...data, 1);
  ctx.strokeStyle = '#73daca';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  data.forEach((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - (v / max) * h * 0.9;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
  // fill
  ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
  ctx.fillStyle = 'rgba(115,218,202,0.1)';
  ctx.fill();
}

async function refresh() {
  try {
    const r = await fetch('/api/state');
    const d = await r.json();

    document.getElementById('cpu').textContent = d.cpu;
    document.getElementById('temp').textContent = d.temp;
    document.getElementById('pool').textContent = d.pool;
    document.getElementById('uptime').textContent = d.uptime > 0 ? fmt(d.uptime) : '—';
    document.getElementById('ping').textContent = d.ping > 0 ? d.ping + ' ms' : '—';

    const statusEl = document.getElementById('status');
    statusEl.textContent = d.status;
    statusEl.className = 'stat-value status-' + d.status.toLowerCase();

    const hrEl = document.getElementById('hashrate-big');
    hrEl.textContent = d.hashrate.toFixed(1);
    hrEl.classList.remove('flash');
    void hrEl.offsetWidth;  // reflow to restart animation
    hrEl.classList.add('flash');
    history.push(d.hashrate);
    if (history.length > 60) history.shift();
    drawSpark(document.getElementById('spark-canvas'), history);

    document.getElementById('payout-label').textContent =
      `POOL PAYOUTS (${d.currency.toUpperCase()})`;

    if (d.xmr_price > 0) {
      document.getElementById('payouts').innerHTML =
        `Pending: <b style="color:var(--yellow)">${d.pending_xmr.toFixed(6)} XMR</b> ` +
        `<span class="payout-fiat">(${d.pending_fiat.toFixed(2)} ${d.currency.toUpperCase()})</span><br>` +
        `Paid: <b style="color:var(--yellow)">${d.paid_xmr.toFixed(4)} XMR</b> ` +
        `<span class="payout-fiat">(${d.paid_fiat.toFixed(2)} ${d.currency.toUpperCase()})</span>`;
    }

    document.getElementById('algo').textContent = 'Algo: ' + d.algo;
    const tg = document.getElementById('threads');
    tg.innerHTML = d.threads.map((v, i) =>
      `<span class="thread-row"><span class="thread-id">T${i}:</span> ${v.toFixed(1)} H/s</span>`
    ).join('');

    document.getElementById('share-label').textContent =
      `Shares: ${d.shares} / ${d.target_shares}`;
    const pct = d.target_shares > 0 ? Math.min(100, (d.shares / d.target_shares) * 100) : 0;
    document.getElementById('progress-fill').style.width = pct + '%';

  } catch(e) { /* XMRig offline */ }
}

refresh();
setInterval(refresh, 3000);
window.addEventListener('resize', () => {
  drawSpark(document.getElementById('spark-canvas'), history);
});
</script>
</body>
</html>"""


@_flask_app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@_flask_app.route("/api/state")
def api_state():
    return jsonify(get_state())


_flask_error: str | None = None

def _run_flask():
    from waitress import serve
    serve(_flask_app, host="127.0.0.1", port=WEB_PORT)


# ─────────────────────────────────────────────
# Config Editor Modal
# ─────────────────────────────────────────────

class ConfigEditorScreen(ModalScreen):
    DEFAULT_CSS = """
    ConfigEditorScreen { align: center middle; }
    #editor-box {
        width: 70; height: auto;
        background: #10141e; border: double #ff6600; padding: 1 2;
    }
    #editor-title {
        color: #ff6600; text-style: bold;
        content-align: center middle; width: 100%;
        margin-bottom: 1; border-bottom: solid #1c202a;
    }
    .field-label { color: #7aa2f7; margin-top: 1; height: 1; }
    Input {
        background: #0b0e14; border: solid #1c202a;
        color: #acb0d0; margin-bottom: 0;
    }
    Input:focus { border: solid #ff6600; }
    #editor-hint { color: #565f89; margin-top: 1; height: 1; }
    #btn-row { margin-top: 1; height: 3; align: center middle; }
    Button { margin: 0 1; }
    #btn-save { background: #ff6600; color: #0b0e14; border: none; }
    #btn-save:hover { background: #ff8833; }
    #btn-cancel { background: #1c202a; color: #acb0d0; border: solid #565f89; }
    #btn-cancel:hover { background: #2a2f3d; }
    #btn-save-restart { background: #9ece6a; color: #0b0e14; border: none; }
    #btn-save-restart:hover { background: #b5e580; }
    """

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg

    def _get_arg(self, *flags: str) -> str:
        args = self.cfg.get("xmrig_args", [])
        for i, x in enumerate(args):
            if x in flags and i + 1 < len(args):
                return args[i + 1]
        return ""

    def compose(self) -> ComposeResult:
        with Vertical(id="editor-box"):
            yield Static("⚙  CONFIG EDITOR", id="editor-title")
            yield Label("XMRig Path", classes="field-label")
            yield Input(value=self.cfg.get("xmrig_path", ""), id="in_xmrig_path",
                        placeholder="/path/to/xmrig")
            yield Label("Wallet Address  (-u)", classes="field-label")
            yield Input(value=self._get_arg("-u"), id="in_wallet",
                        placeholder="your wallet address")
            yield Label("Pool URL  (-o)", classes="field-label")
            yield Input(value=self._get_arg("-o", "--url"), id="in_pool",
                        placeholder="pool.example.com:3333")
            yield Label("Threads  (-t)", classes="field-label")
            yield Input(value=self._get_arg("-t", "--threads"), id="in_threads",
                        placeholder="e.g. 4")
            yield Label("Currency (USD/EUR/GBP...)", classes="field-label")
            yield Input(value=self.cfg.get("currency", "USD"), id="in_currency",
                        placeholder="USD")
            yield Label("Target Shares", classes="field-label")
            yield Input(value=str(self.cfg.get("target_shares", 200)),
                        id="in_target_shares", placeholder="200")
            yield Static("Tab to move between fields", id="editor-hint")
            with Horizontal(id="btn-row"):
                yield Button("Save", id="btn-save")
                yield Button("Save & Restart", id="btn-save-restart")
                yield Button("Cancel", id="btn-cancel")

    def _build_updated_cfg(self) -> dict:
        new_cfg = dict(self.cfg)
        new_cfg["xmrig_path"] = self.query_one("#in_xmrig_path", Input).value.strip()
        new_cfg["currency"]   = self.query_one("#in_currency", Input).value.strip().upper() or "USD"
        try:
            new_cfg["target_shares"] = int(self.query_one("#in_target_shares", Input).value.strip())
        except ValueError:
            new_cfg["target_shares"] = self.cfg.get("target_shares", 200)
        wallet  = self.query_one("#in_wallet",  Input).value.strip()
        pool    = self.query_one("#in_pool",    Input).value.strip()
        threads = self.query_one("#in_threads", Input).value.strip()
        args = list(new_cfg.get("xmrig_args", []))

        def _set_arg(flag: str, value: str) -> None:
            if not value:
                return
            try:
                idx = args.index(flag)
                args[idx + 1] = value if idx + 1 < len(args) else args.append(value)
            except ValueError:
                args.extend([flag, value])

        if wallet:  _set_arg("-u", wallet)
        if pool:    _set_arg("-o", pool)
        if threads: _set_arg("-t", threads)
        new_cfg["xmrig_args"] = args
        return new_cfg

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button.id
        if btn == "btn-cancel":
            self.dismiss(None)
            return
        new_cfg = self._build_updated_cfg()
        save_dash_config(new_cfg)
        self.dismiss(("restart" if btn == "btn-save-restart" else "saved", new_cfg))


# ─────────────────────────────────────────────
# Main TUI App
# ─────────────────────────────────────────────

class XMRigSleek(App):
    TITLE = "XMRIG ENGINE MANAGER"
    BINDINGS = [
        ("q", "quit",         "Quit"),
        ("r", "restart",      "Restart"),
        ("p", "pause_resume", "Pause/Resume"),
        ("e", "open_editor",  "Edit Config"),
        ("w", "toggle_web",   "Web On/Off"),
    ]

    CSS = """
    Screen { background: #0b0e14; color: #cdcecf; }
    #main-container { layout: grid; grid-size: 2; grid-columns: 1fr 1.3fr; padding: 1; }
    #left-pane  { border-right: solid #1c202a; padding: 0 2; background: #0b0e14; }
    #right-pane { padding: 0 2; }
    .header-label {
        color: #565f89; text-style: bold;
        margin: 1 0; border-bottom: solid #1c202a; width: 100%;
    }
    .stat-line   { height: 1; margin-bottom: 0; }
    .label       { width: 15; color: #7aa2f7; }
    .value       { color: #acb0d0; text-style: bold; }
    #hash-digits { color: #9ece6a; height: 3; margin: 1 0; content-align: center middle; }
    #hash_graph  { width: 100%; height: 4; color: #73daca; margin-top: 1; }
    ProgressBar  { width: 100%; margin: 1 0; }
    ProgressBar > .progress-bar--bar { color: #73daca; }
    #miner-display {
        background: #10141e; padding: 1;
        border: round #1c202a; height: 1fr; margin-bottom: 1;
    }
    #payout_display { color: #e0af68; margin-bottom: 1; }
    #logo-container { margin-bottom: 1; content-align: center middle; }
    #pause-banner {
        background: #e0af68; color: #0b0e14; text-style: bold;
        content-align: center middle; width: 100%; height: 1; display: none;
    }
    #pause-banner.visible { display: block; }
    #web-banner {
        background: #7aa2f7; color: #0b0e14; text-style: bold;
        content-align: center middle; width: 100%; height: 1; display: none;
    }
    #web-banner.visible { display: block; }
    """

    def __init__(self, user_cfg: dict):
        super().__init__()
        self.user_cfg      = user_cfg
        self.currency      = user_cfg.get("currency", "USD").lower()
        args               = user_cfg.get("xmrig_args", [])
        self.wallet        = next((args[i + 1] for i, x in enumerate(args) if x == "-u"), None)
        self.history: list = []
        self.xmr_price     = 0.0
        self.miner_process = None
        self.is_paused     = False
        self.web_active    = False
        update_state(
            currency=self.currency,
            target_shares=user_cfg.get("target_shares", 200),
        )

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("⏸  MINER PAUSED — Press P to resume", id="pause-banner")
        yield Static(f"🌐  WEB DASHBOARD ACTIVE — http://127.0.0.1:{WEB_PORT}  — Press W to stop",
                     id="web-banner")
        with Container(id="main-container"):
            with Vertical(id="left-pane"):
                yield Static(ISOMETRIC_LOGO, id="logo-container")
                yield Label("SYSTEM STATUS", classes="header-label")
                with Horizontal(classes="stat-line"):
                    yield Label("CPU Util:", classes="label")
                    yield Label("0%", id="cpu_val", classes="value")
                with Horizontal(classes="stat-line"):
                    yield Label("CPU Temp:", classes="label")
                    yield Label("N/A", id="temp_val", classes="value")
                with Horizontal(classes="stat-line"):
                    yield Label("Miner:", classes="label")
                    yield Label("STARTING", id="miner_status_val", classes="value")
                yield Label("HASHRATE TREND", classes="header-label")
                yield Digits("0.0", id="hash-digits")
                yield Static("", id="hash_graph")
                yield Label(f"POOL PAYOUTS ({self.currency.upper()})", classes="header-label")
                yield Static("Syncing market data...", id="payout_display")
            with Vertical(id="right-pane"):
                yield Label("LIVE ENGINE", classes="header-label")
                yield Static("Polling...", id="miner_display")
                yield Label("SESSION PROGRESS", classes="header-label")
                yield Label(f"Shares: 0 / {self.user_cfg['target_shares']}", id="share_text")
                yield ProgressBar(total=self.user_cfg["target_shares"],
                                  id="share_bar", show_eta=False)
        yield Footer()

    def on_mount(self) -> None:
        self._launch_miner()
        self.set_interval(3,  self.poll_miner_api)
        self.set_interval(60, self.update_market_price)
        self.set_interval(30, self.poll_pool_api)

    # ── Miner lifecycle ──────────────────────────────────────────────────────

    def _launch_miner(self) -> None:
        try:
            if self.user_cfg.get("mode") == "args":
                cmd   = [self.user_cfg["xmrig_path"]] + self.user_cfg.get("xmrig_args", [])
                flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
                self.miner_process = subprocess.Popen(cmd, creationflags=flags)
                self.is_paused = False
        except Exception as e:
            self.notify(f"Failed to launch XMRig: {e}", severity="error")

    def _terminate_miner(self) -> None:
        if self.miner_process:
            try:
                if self.is_paused:
                    self._do_resume()
                self.miner_process.terminate()
                self.miner_process.wait(timeout=3)
            except Exception:
                try:
                    self.miner_process.kill()
                except Exception:
                    pass
            finally:
                self.miner_process = None

    def _do_pause(self) -> None:
        if not self.miner_process:
            return
        try:
            psutil.Process(self.miner_process.pid).suspend()
            self.is_paused = True
        except psutil.NoSuchProcess:
            self.notify("Miner process not found.", severity="warning")
        except Exception as e:
            self.notify(f"Pause failed: {e}", severity="error")

    def _do_resume(self) -> None:
        if not self.miner_process:
            return
        try:
            psutil.Process(self.miner_process.pid).resume()
            self.is_paused = False
        except psutil.NoSuchProcess:
            self.notify("Miner process not found.", severity="warning")
        except Exception as e:
            self.notify(f"Resume failed: {e}", severity="error")

    # ── Keybind actions ──────────────────────────────────────────────────────

    def action_restart(self) -> None:
        self._terminate_miner()
        self._launch_miner()
        self.notify("Miner restarted.", severity="information")

    def action_pause_resume(self) -> None:
        if not self.miner_process:
            self.notify("No miner process running.", severity="warning")
            return
        banner = self.query_one("#pause-banner")
        status = self.query_one("#miner_status_val")
        if self.is_paused:
            self._do_resume()
            banner.remove_class("visible")
            status.update("[green]RUNNING[/]")
            self.notify("Miner resumed.", severity="information")
        else:
            self._do_pause()
            banner.add_class("visible")
            status.update("[yellow]PAUSED[/]")
            self.notify("Miner paused.", severity="warning")
        update_state(paused=self.is_paused)

    def action_open_editor(self) -> None:
        self.push_screen(ConfigEditorScreen(self.user_cfg), self._on_editor_result)

    def _on_editor_result(self, result) -> None:
        if result is None:
            return
        action, new_cfg = result
        self.user_cfg = new_cfg
        self.currency = new_cfg.get("currency", "USD").lower()
        args          = new_cfg.get("xmrig_args", [])
        self.wallet   = next((args[i + 1] for i, x in enumerate(args) if x == "-u"), None)
        target        = new_cfg.get("target_shares", 200)
        self.query_one("#share_text").update(f"Shares: 0 / {target}")
        self.query_one("#share_bar").update(total=target)
        update_state(currency=self.currency, target_shares=target)
        self.notify("Config saved.", severity="information")
        if action == "restart":
            self._terminate_miner()
            self._launch_miner()
            self.notify("Miner restarted with new config.", severity="information")

    def action_toggle_web(self) -> None:
        global _flask_thread, _flask_error
        banner = self.query_one("#web-banner")
        if self.web_active:
            self.web_active = False
            banner.remove_class("visible")
            update_state(web_active=False)
            self.notify("Web dashboard deactivated. Restart app to fully stop Flask.",
                        severity="warning")
        else:
            _flask_error = None
            if _flask_thread is None or not _flask_thread.is_alive():
                _flask_thread = threading.Thread(target=_run_flask, daemon=True)
                _flask_thread.start()
            # Give Flask a moment to bind, then check for errors
            import time; time.sleep(1)
            if _flask_error:
                self.notify(f"Flask failed to start: {_flask_error}", severity="error")
                return
            if not _flask_thread.is_alive():
                self.notify("Flask thread died immediately — port 4727 may be in use.", severity="error")
                return
            self.web_active = True
            banner.add_class("visible")
            update_state(web_active=True)
            self.notify(f"Web dashboard active → http://127.0.0.1:{WEB_PORT}",
                        severity="information")

    def on_unmount(self) -> None:
        self._terminate_miner()

    # ── Background workers ───────────────────────────────────────────────────

    @work(exclusive=True, thread=True)
    def update_market_price(self) -> None:
        try:
            r = requests.get(f"{PRICE_API}{self.currency}", timeout=5).json()
            self.xmr_price = float(r["monero"][self.currency])
            update_state(xmr_price=self.xmr_price)
        except Exception:
            pass

    @work(exclusive=True, thread=True)
    def poll_miner_api(self) -> None:
        cpu  = psutil.cpu_percent()
        temp = "N/A"
        if hasattr(psutil, "sensors_temperatures"):
            try:
                t_data = psutil.sensors_temperatures().get("coretemp", [])
                if t_data:
                    temp = f"{int(t_data[0].current)}°C"
            except Exception:
                pass

        data = None
        if not self.is_paused:
            for url in API_ENDPOINTS:
                try:
                    r = requests.get(url, timeout=0.8)
                    if r.status_code == 200:
                        data = r.json()
                        break
                except Exception:
                    continue

        self.call_from_thread(self.update_ui, cpu, temp, data)

    def _render_ascii_graph(self, data: list) -> str:
        """Render a braille dot graph. Each char = 2x4 dots giving high resolution."""
        if len(data) < 2:
            return "[#1c202a]  No data yet…[/]"

        width    = 52   # braille chars wide
        height   = 4    # braille chars tall
        dot_cols = width * 2
        dot_rows = height * 4

        # Sample to fit dot columns, pad left if short
        if len(data) > dot_cols:
            step    = len(data) / dot_cols
            sampled = [data[int(i * step)] for i in range(dot_cols)]
        else:
            sampled = list(data)
            while len(sampled) < dot_cols:
                sampled.insert(0, sampled[0])

        lo   = min(sampled)
        hi   = max(sampled)
        span = hi - lo if hi != lo else 1.0

        def to_dot_row(v):
            return int((v - lo) / span * (dot_rows - 1))

        dot_heights = [to_dot_row(v) for v in sampled]

        # Braille bit layout per cell (2 cols x 4 rows, top-to-bottom):
        # col0 bits: row0=0x01 row1=0x02 row2=0x04 row3=0x40
        # col1 bits: row0=0x08 row1=0x10 row2=0x20 row3=0x80
        col0_bits = [0x01, 0x02, 0x04, 0x40]
        col1_bits = [0x08, 0x10, 0x20, 0x80]

        lines = []
        for char_row in range(height):
            row_str = ""
            dot_row_base = char_row * 4
            for char_col in range(width):
                bits         = 0
                dot_col_base = char_col * 2
                for c in range(2):
                    h = dot_heights[dot_col_base + c]
                    for r in range(4):
                        if h >= dot_row_base + r:
                            bits |= (col0_bits if c == 0 else col1_bits)[3 - r]
                row_str += chr(0x2800 + bits)
            lines.append(row_str)

        lines = list(reversed(lines))  # top of graph = top of display
        labeled = []
        for i, line in enumerate(lines):
            if i == 0:
                labeled.append(f"[#73daca]{line}[/] [#565f89]{hi:.0f}[/]")
            elif i == len(lines) - 1:
                labeled.append(f"[#73daca]{line}[/] [#565f89]{lo:.0f}[/]")
            else:
                labeled.append(f"[#73daca]{line}[/]")
        return "\n".join(labeled)

    def update_ui(self, cpu, temp, data) -> None:
        update_state(cpu=f"{cpu}%", temp=temp)
        try:
            self.query_one("#cpu_val").update(f"{cpu}%")
            self.query_one("#temp_val").update(temp)
        except Exception:
            return  # modal is open, DOM not queryable — state still updated above

        status_widget = self.query_one("#miner_status_val")
        if self.is_paused:
            status_widget.update("[yellow]PAUSED[/]")
            update_state(status="paused")
        elif not data:
            status_widget.update("[red]OFFLINE[/]")
            self.query_one("#miner_display").update("[red]OFFLINE — XMRig not responding[/]")
            update_state(status="offline")
            return
        else:
            status_widget.update("[green]RUNNING[/]")
            update_state(status="running")

        if not data:
            return

        hr_total = data.get("hashrate", {}).get("total", [0.0])
        hr       = hr_total[0] if hr_total and hr_total[0] is not None else 0.0
        self.query_one("#hash-digits").update(f"{hr:.1f}")
        self.history.append(hr)
        if len(self.history) > 120:
            self.history.pop(0)
        self.query_one("#hash_graph").update(self._render_ascii_graph(self.history))

        shares = data.get("results", {}).get("shares_good", 0)
        target = self.user_cfg.get("target_shares", 200)
        self.query_one("#share_text").update(f"Shares: {shares} / {target}")
        self.query_one("#share_bar").update(total=target, progress=shares)

        threads     = data.get("hashrate", {}).get("threads", [])
        thread_vals = [t[0] if t and t[0] is not None else 0.0 for t in threads]
        conn        = data.get("connection", {})

        content = f"[bold cyan]Algo: {data.get('algo', '???')}[/]\n" + "─" * 45 + "\n"
        for i, val in enumerate(thread_vals):
            content += f"T{i:<2}: {val:>8.1f} H/s  " + ("\n" if (i + 1) % 2 == 0 else "")
        self.query_one("#miner_display").update(content)

        update_state(
            hashrate=hr,
            history=list(self.history),
            algo=data.get("algo", "???"),
            shares=shares,
            target_shares=target,
            threads=thread_vals,
            pool=conn.get("pool", "—"),
            uptime=data.get("uptime", 0),
            ping=conn.get("ping", 0),
        )

    @work(exclusive=True, thread=True)
    def poll_pool_api(self) -> None:
        if not self.wallet:
            return
        try:
            r        = requests.get(f"{POOL_API_BASE}{self.wallet}/stats", timeout=10).json()
            due_xmr  = float(r.get("amtDue",  0)) / 1e12
            paid_xmr = float(r.get("amtPaid", 0)) / 1e12
            cur_sym  = self.currency.upper()
            due_fiat  = due_xmr  * self.xmr_price
            paid_fiat = paid_xmr * self.xmr_price
            display = (
                f"Pending: [bold #e0af68]{due_xmr:.6f} XMR[/] ([#9ece6a]{due_fiat:.2f} {cur_sym}[/])\n"
                f"Paid:    [bold #e0af68]{paid_xmr:.4f} XMR[/] ([#9ece6a]{paid_fiat:.2f} {cur_sym}[/])"
            )
            self.call_from_thread(self.query_one("#payout_display").update, display)
            update_state(
                pending_xmr=due_xmr, paid_xmr=paid_xmr,
                pending_fiat=due_fiat, paid_fiat=paid_fiat,
            )
        except Exception:
            pass


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg = load_dash_config()
    if cfg:
        XMRigSleek(cfg).run()
    else:
        print(f"[ERROR] '{DASH_CONFIG}' not found. Please create it before launching.")
        sys.exit(1)
