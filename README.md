# xmrig-dash

![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square)

A TUI & web dashboard for monitoring and managing [XMRig](https://github.com/xmrig/xmrig), built with [Textual](https://github.com/Textualize/textual) and Flask.

---

## Features

- Full terminal dashboard with hashrate, per-thread stats, pool payouts, and session progress.
- A hashrate trend graph using Unicode braille characters.
- Press `W` to serve an auto-refreshing HTML dashboard on `http://127.0.0.1:4727`.
- Edit pool, wallet, threads, and more without leaving the TUI (`E`).
- Suspend the miner process without killing it (`P`), useful while doing other intensive tasks :D
- Live XMR price using CoinGecko, payouts shown in your local currency
- Pending and paid balances pulled from MoneroOcean API

---

## Screenshots

<details>
  <summary>TUI View</summary>
  
  ![TUI](https://github.com/SpeedyCoder1192/xmrig-dash/blob/e29e1dcf5d5aa48f555ea0fef0f6fe78a155a84c/images/image.png)
  
</details>

<details>
  <summary>Web View</summary>
  
  ![Web](https://github.com/SpeedyCoder1192/xmrig-dash/blob/94421262237b83819f895bea10ef48d571119611/images/web.png)
  
</details>

---

## Requirements

```
pip install textual psutil requests flask waitress
```

XMRig must be running with its HTTP API enabled:

```json
"--http-host": "127.0.0.1",
"--http-port": "16000"
```

---

## Installation

```bash
git clone https://github.com/SpeedyCoder1192/xmrig-dashboard
cd xmrig-dashboard
pip install -r requirements.txt
```

---

## Configuration

Create `dash_config.json` in the same directory as the script:

```json
{
  "mode": "args",
  "xmrig_path": "full path to xmrig executable",
  "xmrig_args": [
    "-o", "pool.moneroocean.stream:10008",
    "-u", "wallet address",
    "-t", "4",
    "--http-host", "127.0.0.1",
    "--http-port", "16000"
  ],
  "currency": "USD",
  "target_shares": 200
}
```

| Field | Description |
|-------|-------------|
| `mode` | Set to `"args"` to have the dashboard launch XMRig automatically, or set to `"config"` to use the config.json in XMRig's directory |
| `xmrig_path` | Full path to your XMRig executable |
| `xmrig_args` | Arguments passed to XMRig on launch |
| `currency` | Any CoinGecko-supported currency code (`USD`, `EUR`, `GBP`, etc.) |
| `target_shares` | Share count goal shown in the progress bar |

> **Note:** `--http-host` and `--http-port` in `xmrig_args` are required for the dashboard to poll XMRig's API.

---

## Usage

```bash
python xmrig_dash.py
```

### Keybinds

| Key | Action |
|-----|--------|
| `Q` | Quit |
| `R` | Restart miner |
| `P` | Pause / Resume miner |
| `E` | Open config editor |
| `W` | Toggle web dashboard on/off |

### Web Dashboard

Press `W` inside the TUI to start the Flask web server. Then open:

```
http://127.0.0.1:4727
```

The web dashboard mirrors the TUI and auto-refreshes every 3 seconds. Press `W` again to deactivate (requires app restart to fully stop Flask).

---

## Pool Support

The dashboard currently pulls payout stats from [MoneroOcean](https://moneroocean.stream). If you use a different pool, the payout section will show `Syncing…` but all other stats will work normally.

---

## Notes

- CPU temperature requires admin/root on most systems. If shown as `N/A`, run the script elevated or use a tool like OpenHardwareMonitor (Windows).
- The hash trend graph needs at least ~30 seconds of data before it shows meaningful variance.
- Pausing the miner suspends the process (SIGSTOP on Linux, `NtSuspendProcess` on Windows) — XMRig stays in memory and resumes instantly.

---

## License

MIT — see [LICENSE](https://github.com/SpeedyCoder1192/xmrig-dash/blob/main/LICENSE)

---

## Disclaimer

This project is a monitoring tool only. Make sure your XMRig usage complies with Monero Community Guidelines and the terms of service of any pool or platform you mine on.
