# TV Demo Runbook — Tarang Dashboard on a 65" TV (HDMI from laptop)

## Why this is needed
The dashboard is tuned for the small **800×480 kiosk LCD**. On a TV the browser
reports a **1920×1080 (or larger) viewport**, so the desktop layout renders with
11–22px fonts and looks tiny from couch distance.

**Fix:** launch the browser with `--force-device-scale-factor=2.0`. This scales
**every** element equally (fonts, icons, ECG waveform, top bar, patient rail) —
the same device-zoom mechanism the Pi kiosk already uses (`TARANG_SCALE_FACTOR`
in `start_kiosk.sh`). At 2.0 on a 1080p TV, the effective viewport becomes
960×540, so the app renders its own compact kiosk layout at 2× — big and bold.
The ECG canvas already handles `devicePixelRatio`, so traces stay crisp.

---

## One-time venue setup (~3 min)
- [ ] Laptop → TV via HDMI; **Win+P → "Second screen only"** (or "Extend")
- [ ] Windows Display settings (TV): **1920×1080 @ 60Hz, Scale 100%**
- [ ] TV remote: set that HDMI input to **"Just Scan" / "PC mode"** (kills overscan cropping)
- [ ] Sound: set Windows output to the TV if alarms should play on TV speakers
- [ ] Laptop plugged in; notifications/Focus-assist off

## Demo-day sequence
1. Start the stack on the laptop:
   - Backend (local, or point the frontend at the Pi — check `.env` if needed)
   - Frontend, from `projects\tarang-rpi\dashboard\frontend`:
     `npm run dev`  (or `npm run build` then `npm start` for smoother performance)
2. Launch the big-screen browser:
   ```
   start_tv_demo.bat
   ```
   Defaults: `http://localhost:3000`, scale `2.0`. Custom examples:
   ```
   start_tv_demo.bat http://localhost:3000 1.75
   start_tv_demo.bat http://192.168.1.50:3000 2.5
   ```
3. If the window opened on the laptop screen: **Win+Shift+→** to move it, then **F11**.
4. Sanity check on the TV: UI fills the screen, **no scrollbars**, waveform crisp,
   text huge. Alarm audio plays without needing a click (launcher passes
   `--autoplay-policy=no-user-gesture-required`).

## Scale cheat sheet
| Setup | Scale | Result |
|---|---|---|
| 1080p TV *(default)* | **2.0** | Compact kiosk layout at 2× — everything huge (recommended) |
| 1080p TV | 1.75 | Full desktop layout (patient rail visible) at 1.75× |
| 4K TV | 2.5 – 3.0 | Same layouts, more headroom |
| Laptop screen only | 1.0 | Normal dev view |

## No-launcher fallback (works in any browser)
New Chrome/Edge window → drag to TV → **F11** → **Ctrl+Plus** until it reads
**200%**. Browser zoom is the same uniform scaling, and Chrome remembers it per
site. (`Ctrl+0` resets.)

## Troubleshooting
| Symptom | Fix |
|---|---|
| Still too small | Re-run with 2.25 or 2.5 |
| Screen edges cut off | TV input set to "Just Scan" / PC mode |
| Scale flags seem ignored | A normal browser window was already running — the launcher's throwaway `--user-data-dir` avoids this; otherwise use the Ctrl+Plus fallback |
| Alarm sounds silent | Launcher already passes the autoplay flag; otherwise click the page once |
| Window on wrong screen | Win+Shift+Arrow keys, then F11 |
| Scrollbars appear | Drop scale one notch (e.g. 1.75) |

## Notes
- The launcher uses a throwaway profile at `%TEMP%\tarang_tv_demo_profile`
  (only holds the demo browser session — delete anytime).
- For a locked-down screen (no F11 exit / address bar), change
  `--start-fullscreen` to `--kiosk` in `start_tv_demo.bat`.
- Rehearse once at home on any 1080p monitor (F11) before the real demo.
