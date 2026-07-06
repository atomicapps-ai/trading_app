"""launcher.py — desktop control panel for TradeAgent + Cloudflare tunnel.

A tiny tkinter window (no extra pip deps — tkinter ships with Python) that
runs the app AND the Cloudflare tunnel as subprocesses and can *cleanly* stop
them. This is the fix for "Ctrl+C won't kill it": uvicorn's reload child + the
APScheduler / IB Gateway threads (and cloudflared's own children) can outlive a
Ctrl+C. The launcher tree-kills them instead, and for the app it also kills
whatever still holds the port — so an orphan you can't reach is stoppable here.

Layout (combined panel):
  * A bright MODE banner (RESEARCH / PAPER / LIVE) read from settings.yaml.
  * TradeAgent app row   — Start / Stop / Open, dev + phone + port options.
  * Cloudflare tunnel row — Start / Stop, tunnel name, auto-start-with-app.
  * Start all / Stop all.
  * A tabbed log (App | Tunnel).

Run it:
    Double-click  "Start TradeAgent.bat"   (Windows — no console window)
    or:           python launcher.py
"""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"
DEFAULT_PORT = 5000
DEFAULT_TUNNEL = "tindex-app"
TUNNEL_HOSTNAME = "app.tindex.ai"

# Windows process-creation flags (defined here so the module imports on POSIX).
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000

# Child output is redirected to these files and tailed into the log panes.
# (We DON'T use a pipe: on Windows the app must run under a real console —
# see _popen — and file capture is the reliable way to read it back.)
_LOG_DIR = ROOT / "data" / "launcher_logs"
_APP_LOG = _LOG_DIR / "app.log"
_TUN_LOG = _LOG_DIR / "tunnel.log"


# --------------------------------------------------------------------------- #
# Process helpers — no external dependencies (no psutil).                      #
# --------------------------------------------------------------------------- #
def pid_on_port(port: int) -> int | None:
    """Return the PID LISTENING on `port`, or None. Cross-platform best-effort."""
    try:
        if IS_WIN:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True,
                creationflags=_CREATE_NO_WINDOW,
            ).stdout
            for line in out.splitlines():
                parts = line.split()
                if (len(parts) >= 5 and parts[3] == "LISTENING"
                        and parts[1].endswith(f":{port}")):
                    return int(parts[4])
            return None
        r = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True, text=True,
        )
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.split()[0])
    except Exception:
        pass
    try:
        r = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if f":{port} " in line and "pid=" in line:
                return int(line.split("pid=", 1)[1].split(",", 1)[0])
    except Exception:
        pass
    return None


def _console_python(exe: str) -> str:
    """Prefer python.exe over pythonw.exe on Windows.

    The app (uvicorn + asyncio + ib_insync) is a CONSOLE program — launched
    under the windowless pythonw.exe it has no usable std streams / console and
    the server exits immediately with code 0. We run the console python.exe in
    a HIDDEN window instead (see _popen), which is exactly the invocation that
    works from a terminal.
    """
    if IS_WIN and exe.lower().endswith("pythonw.exe"):
        cand = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.exists(cand):
            return cand
    return exe


def _popen(cmd: list[str], log_path: Path) -> subprocess.Popen:
    """Spawn `cmd` in its own process group, output → `log_path` (tailed).

    Windows: run the console python.exe with a HIDDEN console window (not
    CREATE_NO_WINDOW, which gives no console at all and kills the server).
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [_console_python(cmd[0]), *cmd[1:]]
    log_fh = open(log_path, "w", buffering=1, encoding="utf-8", errors="replace")
    # Unbuffered Python so log lines reach the file (and the pane) promptly.
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    kwargs: dict = dict(
        cwd=str(ROOT), env=env,
        stdout=log_fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
    )
    if IS_WIN:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE — console exists but its window is hidden
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = _CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(cmd, **kwargs)
    finally:
        # Child holds its own dup of the handle; drop ours.
        try:
            log_fh.close()
        except Exception:
            pass


def start_server(mode: str, host: str, port: int) -> subprocess.Popen:
    """Spawn run.py in its own process group so the whole tree is killable."""
    return _popen([sys.executable, str(ROOT / "run.py"), mode,
                   "--host", host, "--port", str(port)], _APP_LOG)


def start_tunnel(name: str) -> subprocess.Popen:
    """Spawn `cloudflared tunnel run <name>` in its own process group."""
    exe = "cloudflared.exe" if IS_WIN else "cloudflared"
    return _popen([exe, "tunnel", "run", name], _TUN_LOG)


def _tree_kill(pid: int) -> None:
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, creationflags=_CREATE_NO_WINDOW)
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def stop_proc(proc: subprocess.Popen | None, *, port: int | None = None) -> None:
    """Kill a subprocess tree. If `port` is given, also kill whatever still
    holds it (covers an orphan/external server the launcher didn't start)."""
    if proc is not None and proc.poll() is None:
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, creationflags=_CREATE_NO_WINDOW)
            else:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(pgid, signal.SIGKILL)
        except Exception:
            pass
    if port is not None:
        leftover = pid_on_port(port)
        if leftover:
            _tree_kill(leftover)


def read_mode() -> str:
    """Read the trading mode from settings.yaml (research/paper/live).

    Defaults to 'paper' when settings.yaml is absent (matches the app's own
    default). Best-effort: uses PyYAML if available, else a tiny regex.
    """
    path = ROOT / "settings.yaml"
    if not path.exists():
        return "paper"
    try:
        import yaml  # available in the project venv
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        app = data.get("app") or {}
        return str(app.get("mode") or data.get("mode") or "paper").lower()
    except Exception:
        # Regex fallback — find an `app:` block then its `mode:` line.
        try:
            import re
            text = path.read_text(encoding="utf-8")
            m = re.search(r"^\s*mode:\s*([A-Za-z]+)", text, re.M)
            if m:
                return m.group(1).lower()
        except Exception:
            pass
    return "paper"


# --------------------------------------------------------------------------- #
# GUI                                                                          #
# --------------------------------------------------------------------------- #
def main() -> None:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext

    # Give Windows a stable app identity so the taskbar groups the window with
    # the pinned "TradeAgent" shortcut (and shows our icon, not python's).
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TradeAgent.Launcher")
        except Exception:
            pass

    BG, PANEL, FG, MUTED = "#13151f", "#1b1e2b", "#e6e8ef", "#8b90a0"
    GREEN, RED, AMBER, BLUE = "#3fb950", "#f85149", "#d29922", "#4493f8"
    # Mode banner colors — LIVE is deliberately alarming.
    MODE_STYLE = {
        "live":     ("#f85149", "#ffffff", "⚠  LIVE — REAL MONEY"),
        "paper":    ("#d29922", "#0b0d13", "PAPER trading"),
        "research": ("#4493f8", "#0b0d13", "RESEARCH — no broker"),
    }

    st = {
        "app_proc": None, "tun_proc": None,
        "app_log": queue.Queue(), "tun_log": queue.Queue(),
        "tun_connected": False,
    }

    root = tk.Tk()
    root.title("TradeAgent Launcher")
    root.configure(bg=BG)
    root.geometry("660x560")
    # Window / taskbar icon (best-effort — .ico only exists on Windows paths).
    try:
        _ico = ROOT / "static" / "icons" / "tradeagent.ico"
        if _ico.exists():
            root.iconbitmap(default=str(_ico))
    except Exception:
        pass
    root.minsize(560, 480)

    # ---- MODE banner ------------------------------------------------------
    mode_banner = tk.Label(root, text="", font=("Segoe UI", 13, "bold"),
                           pady=8)
    mode_banner.pack(fill="x")

    def _panel(parent) -> tk.Frame:
        f = tk.Frame(parent, bg=PANEL)
        f.pack(fill="x", padx=12, pady=(10, 0))
        return f

    def _dot(parent) -> tuple[tk.Canvas, int]:
        c = tk.Canvas(parent, width=14, height=14, bg=PANEL, highlightthickness=0)
        c.pack(side="left", padx=(10, 8), pady=10)
        return c, c.create_oval(2, 2, 12, 12, fill=MUTED, outline="")

    def _btn(parent, text, color, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=color, fg="#0b0d13",
                         activebackground=color, activeforeground="#0b0d13",
                         relief="flat", font=("Segoe UI", 9, "bold"),
                         padx=11, pady=5, cursor="hand2", bd=0)

    def _chk(parent, text, var):
        return tk.Checkbutton(parent, text=text, variable=var, bg=PANEL, fg=FG,
                              selectcolor=BG, activebackground=PANEL,
                              activeforeground=FG, font=("Segoe UI", 9),
                              highlightthickness=0, bd=0)

    # ---- APP panel --------------------------------------------------------
    app_p = _panel(root)
    app_top = tk.Frame(app_p, bg=PANEL); app_top.pack(fill="x")
    app_dot, app_dot_id = _dot(app_top)
    tk.Label(app_top, text="TradeAgent app", bg=PANEL, fg=FG,
             font=("Segoe UI", 11, "bold")).pack(side="left")
    app_status = tk.Label(app_top, text="Stopped", bg=PANEL, fg=MUTED,
                          font=("Segoe UI", 9)); app_status.pack(side="left", padx=8)
    b_app_stop = _btn(app_top, "■ Stop", RED, lambda: do_stop_app())
    b_app_stop.pack(side="right", padx=(0, 10), pady=8)
    b_app_start = _btn(app_top, "▶ Start", GREEN, lambda: do_start_app())
    b_app_start.pack(side="right", padx=(0, 6))
    b_app_open = _btn(app_top, "↗ Open", BLUE, lambda: do_open())
    b_app_open.pack(side="right", padx=(0, 6))

    app_opts = tk.Frame(app_p, bg=PANEL); app_opts.pack(fill="x", padx=10, pady=(0, 10))
    dev_var = tk.BooleanVar(value=False)
    net_var = tk.BooleanVar(value=False)
    port_var = tk.StringVar(value=str(DEFAULT_PORT))
    _chk(app_opts, "dev (hot reload)", dev_var).pack(side="left")
    _chk(app_opts, "phone access (0.0.0.0)", net_var).pack(side="left", padx=(10, 0))
    tk.Label(app_opts, text="port", bg=PANEL, fg=MUTED,
             font=("Segoe UI", 9)).pack(side="left", padx=(12, 4))
    tk.Entry(app_opts, textvariable=port_var, width=6, bg=BG, fg=FG,
             insertbackground=FG, relief="flat",
             font=("Consolas", 10)).pack(side="left")

    # ---- TUNNEL panel -----------------------------------------------------
    tun_p = _panel(root)
    tun_top = tk.Frame(tun_p, bg=PANEL); tun_top.pack(fill="x")
    tun_dot, tun_dot_id = _dot(tun_top)
    tk.Label(tun_top, text="Cloudflare tunnel", bg=PANEL, fg=FG,
             font=("Segoe UI", 11, "bold")).pack(side="left")
    tun_status = tk.Label(tun_top, text="Stopped", bg=PANEL, fg=MUTED,
                          font=("Segoe UI", 9)); tun_status.pack(side="left", padx=8)
    b_tun_stop = _btn(tun_top, "■ Stop", RED, lambda: do_stop_tunnel())
    b_tun_stop.pack(side="right", padx=(0, 10), pady=8)
    b_tun_start = _btn(tun_top, "▶ Start", GREEN, lambda: do_start_tunnel())
    b_tun_start.pack(side="right", padx=(0, 6))

    tun_opts = tk.Frame(tun_p, bg=PANEL); tun_opts.pack(fill="x", padx=10, pady=(0, 10))
    tk.Label(tun_opts, text="tunnel", bg=PANEL, fg=MUTED,
             font=("Segoe UI", 9)).pack(side="left")
    tunnel_var = tk.StringVar(value=DEFAULT_TUNNEL)
    tk.Entry(tun_opts, textvariable=tunnel_var, width=14, bg=BG, fg=FG,
             insertbackground=FG, relief="flat",
             font=("Consolas", 10)).pack(side="left", padx=(6, 8))
    tk.Label(tun_opts, text=f"→ {TUNNEL_HOSTNAME}", bg=PANEL, fg=MUTED,
             font=("Segoe UI", 9)).pack(side="left")
    autotun_var = tk.BooleanVar(value=False)
    _chk(tun_opts, "auto-start tunnel with the app", autotun_var).pack(side="left", padx=(12, 0))

    # ---- ALL buttons ------------------------------------------------------
    allrow = tk.Frame(root, bg=BG); allrow.pack(fill="x", padx=12, pady=(12, 4))
    _btn(allrow, "▶ Start all", GREEN, lambda: do_start_all()).pack(side="left")
    _btn(allrow, "■ Stop all", RED, lambda: do_stop_all()).pack(side="left", padx=(8, 0))

    # ---- LOG (tabbed App | Tunnel) ---------------------------------------
    logbar = tk.Frame(root, bg=BG); logbar.pack(fill="x", padx=12, pady=(8, 0))
    log_which = tk.StringVar(value="app")

    def _mk_logbox():
        return scrolledtext.ScrolledText(
            root, bg=PANEL, fg=MUTED, insertbackground=FG, relief="flat",
            font=("Consolas", 9), wrap="none", state="disabled", height=12)

    app_logbox = _mk_logbox()
    tun_logbox = _mk_logbox()

    def show_log(which: str) -> None:
        log_which.set(which)
        app_logbox.pack_forget(); tun_logbox.pack_forget()
        (app_logbox if which == "app" else tun_logbox).pack(
            fill="both", expand=True, padx=12, pady=(0, 12))
        tab_app.config(bg=(PANEL if which == "app" else BG),
                       fg=(FG if which == "app" else MUTED))
        tab_tun.config(bg=(PANEL if which == "tun" else BG),
                       fg=(FG if which == "tun" else MUTED))

    tab_app = tk.Button(logbar, text="App log", command=lambda: show_log("app"),
                        relief="flat", bd=0, padx=12, pady=4, cursor="hand2",
                        font=("Segoe UI", 9))
    tab_tun = tk.Button(logbar, text="Tunnel log", command=lambda: show_log("tun"),
                        relief="flat", bd=0, padx=12, pady=4, cursor="hand2",
                        font=("Segoe UI", 9))
    tab_app.pack(side="left"); tab_tun.pack(side="left", padx=(2, 0))

    def log(which: str, msg: str) -> None:
        (st["app_log"] if which == "app" else st["tun_log"]).put(
            msg if msg.endswith("\n") else msg + "\n")

    def _pump(proc: subprocess.Popen, which: str) -> None:
        # Follow the child's log FILE (stdout/stderr are redirected there — the
        # app must run under a real console on Windows, so we don't use a pipe).
        q = st["app_log"] if which == "app" else st["tun_log"]
        log_path = _APP_LOG if which == "app" else _TUN_LOG
        f = None
        try:
            for _ in range(100):
                if log_path.exists():
                    break
                time.sleep(0.1)
            f = open(log_path, "r", encoding="utf-8", errors="replace")
            while True:
                line = f.readline()
                if line:
                    q.put(line)
                    if which == "tun" and "Registered tunnel connection" in line:
                        st["tun_connected"] = True
                    continue
                if proc.poll() is not None:
                    rest = f.read()
                    if rest:
                        q.put(rest)
                    break
                time.sleep(0.2)
        except Exception:
            pass
        finally:
            if f:
                try:
                    f.close()
                except Exception:
                    pass

    # ---- actions ----------------------------------------------------------
    def do_start_app() -> None:
        if st["app_proc"] and st["app_proc"].poll() is None:
            return
        try:
            port = int(port_var.get())
        except ValueError:
            messagebox.showerror("Bad port", "Port must be a number."); return
        existing = pid_on_port(port)
        if existing:
            if not messagebox.askyesno(
                    "Port in use",
                    f"Port {port} is already in use (PID {existing}).\n\n"
                    "Stop it and start fresh?"):
                return
            stop_proc(None, port=port)
        mode = "dev" if dev_var.get() else "prod"
        host = "0.0.0.0" if net_var.get() else "127.0.0.1"
        log("app", f"── starting app: {mode} · {host}:{port} ──")
        try:
            proc = start_server(mode, host, port)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Start failed", str(e)); log("app", f"start failed: {e}")
            return
        st["app_proc"] = proc
        threading.Thread(target=_pump, args=(proc, "app"), daemon=True).start()
        if autotun_var.get():
            do_start_tunnel()

    def do_stop_app() -> None:
        port = int(port_var.get()) if port_var.get().isdigit() else DEFAULT_PORT
        log("app", "── stopping app ──")
        stop_proc(st["app_proc"], port=port)
        st["app_proc"] = None

    def do_start_tunnel() -> None:
        if st["tun_proc"] and st["tun_proc"].poll() is None:
            return
        if read_mode() == "live":
            if not messagebox.askyesno(
                    "Expose LIVE app?",
                    "Trading mode is LIVE (real money).\n\n"
                    "Starting the tunnel exposes this app to the internet at "
                    f"{TUNNEL_HOSTNAME}. Continue?"):
                return
        name = tunnel_var.get().strip() or DEFAULT_TUNNEL
        st["tun_connected"] = False
        log("tun", f"── starting tunnel: cloudflared tunnel run {name} ──")
        try:
            proc = start_tunnel(name)
        except FileNotFoundError:
            messagebox.showerror(
                "cloudflared not found",
                "Couldn't find `cloudflared`. Install it and make sure it's on "
                "PATH (see DEPLOY.md).")
            log("tun", "cloudflared not found on PATH")
            return
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Tunnel start failed", str(e))
            log("tun", f"start failed: {e}"); return
        st["tun_proc"] = proc
        threading.Thread(target=_pump, args=(proc, "tun"), daemon=True).start()

    def do_stop_tunnel() -> None:
        log("tun", "── stopping tunnel ──")
        stop_proc(st["tun_proc"])
        st["tun_proc"] = None
        st["tun_connected"] = False

    def do_start_all() -> None:
        do_start_app()
        if not (st["tun_proc"] and st["tun_proc"].poll() is None):
            do_start_tunnel()

    def do_stop_all() -> None:
        do_stop_app(); do_stop_tunnel()

    def do_open() -> None:
        port = port_var.get() if port_var.get().isdigit() else str(DEFAULT_PORT)
        webbrowser.open(f"http://localhost:{port}/")

    # ---- tick loop --------------------------------------------------------
    def _drain(q: queue.Queue, box: tk.Text) -> None:
        wrote = False
        try:
            while True:
                line = q.get_nowait()
                if not wrote:
                    box.configure(state="normal"); wrote = True
                box.insert("end", line)
        except queue.Empty:
            pass
        if wrote:
            n = int(box.index("end-1c").split(".")[0])
            if n > 600:
                box.delete("1.0", f"{n - 600}.0")
            box.see("end"); box.configure(state="disabled")

    def _set_dot(canvas, dot_id, color):
        canvas.itemconfig(dot_id, fill=color)

    def tick() -> None:
        _drain(st["app_log"], app_logbox)
        _drain(st["tun_log"], tun_logbox)

        # Mode banner
        bg, fg, text = MODE_STYLE.get(read_mode(), MODE_STYLE["paper"])
        mode_banner.config(text=text, bg=bg, fg=fg)

        # App status
        ap = st["app_proc"]
        port = int(port_var.get()) if port_var.get().isdigit() else DEFAULT_PORT
        if ap is not None and ap.poll() is None:
            _set_dot(app_dot, app_dot_id, GREEN)
            host = "0.0.0.0" if net_var.get() else "localhost"
            app_status.config(text=f"running · http://{host}:{port}")
            b_app_start.config(state="disabled"); b_app_stop.config(state="normal")
        else:
            if ap is not None and ap.poll() is not None:
                log("app", f"── app exited (code {ap.poll()}) ──"); st["app_proc"] = None
            ext = pid_on_port(port)
            if ext:
                _set_dot(app_dot, app_dot_id, GREEN)
                app_status.config(text=f"running (external) · :{port}")
                b_app_start.config(state="disabled"); b_app_stop.config(state="normal")
            else:
                _set_dot(app_dot, app_dot_id, MUTED)
                app_status.config(text="Stopped")
                b_app_start.config(state="normal"); b_app_stop.config(state="disabled")

        # Tunnel status
        tp = st["tun_proc"]
        if tp is not None and tp.poll() is None:
            if st["tun_connected"]:
                _set_dot(tun_dot, tun_dot_id, GREEN); tun_status.config(text="connected")
            else:
                _set_dot(tun_dot, tun_dot_id, AMBER); tun_status.config(text="starting…")
            b_tun_start.config(state="disabled"); b_tun_stop.config(state="normal")
        else:
            if tp is not None and tp.poll() is not None:
                log("tun", f"── tunnel exited (code {tp.poll()}) ──"); st["tun_proc"] = None
            _set_dot(tun_dot, tun_dot_id, MUTED); tun_status.config(text="Stopped")
            b_tun_start.config(state="normal"); b_tun_stop.config(state="disabled")

        root.after(1000, tick)

    def on_close() -> None:
        running = any([
            st["app_proc"] and st["app_proc"].poll() is None,
            st["tun_proc"] and st["tun_proc"].poll() is None,
            pid_on_port(int(port_var.get()) if port_var.get().isdigit() else DEFAULT_PORT),
        ])
        if running:
            ans = messagebox.askyesnocancel(
                "Quit launcher",
                "The app and/or tunnel are running.\n\n"
                "Yes  — stop everything and quit\n"
                "No   — leave them running and quit\n"
                "Cancel — keep the launcher open")
            if ans is None:
                return
            if ans:
                do_stop_all()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    show_log("app")
    log("app", "Launcher ready. Press ▶ Start.")
    log("tun", "Tunnel idle. Press ▶ Start to expose the app on the internet.")
    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
