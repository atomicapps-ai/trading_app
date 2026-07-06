"""launcher.py — desktop Start/Stop control panel for TradeAgent.

A tiny tkinter window (no extra pip deps — tkinter ships with Python) that
runs the app as a subprocess and can *cleanly* stop it. This is the fix for
"Ctrl+C won't kill it": uvicorn's reload child + the APScheduler / IB Gateway
threads can outlive a Ctrl+C and keep port 5000 bound. The launcher kills the
whole process tree instead, and as a backstop kills anything still holding the
port — so a server started outside the launcher (or an orphan you can't reach)
can be stopped from here too.

Run it:
    Double-click  "Start TradeAgent.bat"   (Windows — no console window)
    or:           python launcher.py

Buttons:  Start · Stop · Restart · Open in browser.
Options:  dev/hot-reload toggle · phone-access (bind 0.0.0.0) · port.
"""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"
DEFAULT_PORT = 5000

# Windows process-creation flags (defined here so the module imports on POSIX).
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000


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
                # proto  local-addr  foreign-addr  state  pid
                if (len(parts) >= 5 and parts[3] == "LISTENING"
                        and parts[1].endswith(f":{port}")):
                    return int(parts[4])
            return None
        # POSIX: prefer lsof, fall back to ss.
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


def start_server(mode: str, host: str, port: int) -> subprocess.Popen:
    """Spawn run.py in its own process group so the whole tree is killable."""
    cmd = [sys.executable, str(ROOT / "run.py"), mode,
           "--host", host, "--port", str(port)]
    kwargs: dict = dict(
        cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=1, text=True,
    )
    if IS_WIN:
        # NEW_PROCESS_GROUP: detach from the launcher's Ctrl+C group.
        # NO_WINDOW: don't pop a second console for the server.
        kwargs["creationflags"] = _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True  # own process group (setsid)
    return subprocess.Popen(cmd, **kwargs)


def _kill_pid(pid: int) -> None:
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, creationflags=_CREATE_NO_WINDOW)
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def stop_server(proc: subprocess.Popen | None, port: int) -> None:
    """Kill our subprocess tree, then anything still holding the port.

    Handles both the launcher-owned process and an orphan/external server.
    """
    if proc is not None and proc.poll() is None:
        try:
            if IS_WIN:
                # /T kills the child tree (run.py's venv re-exec + uvicorn).
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
    # Backstop: whatever still owns the port (e.g. a server we didn't start).
    leftover = pid_on_port(port)
    if leftover:
        _kill_pid(leftover)


# --------------------------------------------------------------------------- #
# GUI                                                                          #
# --------------------------------------------------------------------------- #
def main() -> None:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext

    # Dark palette roughly matching the app.
    BG, PANEL, FG, MUTED = "#13151f", "#1b1e2b", "#e6e8ef", "#8b90a0"
    GREEN, RED, AMBER, BLUE = "#3fb950", "#f85149", "#d29922", "#4493f8"

    state = {"proc": None, "log_q": queue.Queue()}

    root = tk.Tk()
    root.title("TradeAgent Launcher")
    root.configure(bg=BG)
    root.geometry("620x460")
    root.minsize(520, 380)

    # ---- header: status dot + label ---------------------------------------
    header = tk.Frame(root, bg=BG)
    header.pack(fill="x", padx=14, pady=(12, 4))
    dot = tk.Canvas(header, width=14, height=14, bg=BG, highlightthickness=0)
    dot.pack(side="left")
    dot_id = dot.create_oval(2, 2, 12, 12, fill=MUTED, outline="")
    status_lbl = tk.Label(header, text="Stopped", bg=BG, fg=FG,
                          font=("Segoe UI", 13, "bold"))
    status_lbl.pack(side="left", padx=(8, 0))
    url_lbl = tk.Label(header, text="", bg=BG, fg=MUTED, font=("Segoe UI", 10))
    url_lbl.pack(side="right")

    # ---- options row ------------------------------------------------------
    opts = tk.Frame(root, bg=BG)
    opts.pack(fill="x", padx=14, pady=(2, 8))
    dev_var = tk.BooleanVar(value=False)
    net_var = tk.BooleanVar(value=False)
    port_var = tk.StringVar(value=str(DEFAULT_PORT))

    def _chk(parent, text, var):
        return tk.Checkbutton(parent, text=text, variable=var, bg=BG, fg=FG,
                              selectcolor=PANEL, activebackground=BG,
                              activeforeground=FG, font=("Segoe UI", 9),
                              highlightthickness=0, bd=0)

    _chk(opts, "dev (hot reload)", dev_var).pack(side="left")
    _chk(opts, "phone access (0.0.0.0)", net_var).pack(side="left", padx=(10, 0))
    tk.Label(opts, text="port", bg=BG, fg=MUTED,
             font=("Segoe UI", 9)).pack(side="left", padx=(12, 4))
    tk.Entry(opts, textvariable=port_var, width=6, bg=PANEL, fg=FG,
             insertbackground=FG, relief="flat",
             font=("Consolas", 10)).pack(side="left")

    # ---- buttons ----------------------------------------------------------
    btns = tk.Frame(root, bg=BG)
    btns.pack(fill="x", padx=14, pady=(0, 8))

    def mk_btn(text, color, cmd):
        return tk.Button(btns, text=text, command=cmd, bg=color, fg="#0b0d13",
                         activebackground=color, activeforeground="#0b0d13",
                         relief="flat", font=("Segoe UI", 10, "bold"),
                         padx=14, pady=6, cursor="hand2", bd=0)

    def log(msg: str) -> None:
        state["log_q"].put(msg if msg.endswith("\n") else msg + "\n")

    def _pump_output(proc: subprocess.Popen) -> None:
        try:
            for line in iter(proc.stdout.readline, ""):
                state["log_q"].put(line)
        except Exception:
            pass

    def do_start() -> None:
        if state["proc"] and state["proc"].poll() is None:
            return
        try:
            port = int(port_var.get())
        except ValueError:
            messagebox.showerror("Bad port", "Port must be a number.")
            return
        # If something is already on the port, adopt-by-stop rather than fail.
        existing = pid_on_port(port)
        if existing:
            if not messagebox.askyesno(
                    "Port in use",
                    f"Something is already listening on port {port} (PID {existing}).\n\n"
                    "Stop it and start a fresh server?"):
                return
            stop_server(None, port)
        mode = "dev" if dev_var.get() else "prod"
        host = "0.0.0.0" if net_var.get() else "127.0.0.1"
        log(f"── starting: {mode} · {host}:{port} ──")
        try:
            proc = start_server(mode, host, port)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Start failed", str(e))
            log(f"start failed: {e}")
            return
        state["proc"] = proc
        threading.Thread(target=_pump_output, args=(proc,), daemon=True).start()

    def do_stop() -> None:
        port = int(port_var.get()) if port_var.get().isdigit() else DEFAULT_PORT
        log("── stopping ──")
        stop_server(state["proc"], port)
        state["proc"] = None

    def do_restart() -> None:
        do_stop()
        root.after(1200, do_start)

    def do_open() -> None:
        port = port_var.get() if port_var.get().isdigit() else str(DEFAULT_PORT)
        webbrowser.open(f"http://localhost:{port}/")

    b_start = mk_btn("▶ Start", GREEN, do_start)
    b_stop = mk_btn("■ Stop", RED, do_stop)
    b_restart = mk_btn("⟳ Restart", AMBER, do_restart)
    b_open = mk_btn("↗ Open", BLUE, do_open)
    for b in (b_start, b_stop, b_restart, b_open):
        b.pack(side="left", padx=(0, 8))

    # ---- log pane ---------------------------------------------------------
    logbox = scrolledtext.ScrolledText(
        root, bg=PANEL, fg=MUTED, insertbackground=FG, relief="flat",
        font=("Consolas", 9), wrap="none", state="disabled", height=14)
    logbox.pack(fill="both", expand=True, padx=14, pady=(0, 12))

    MAX_LINES = 600

    def _drain_log() -> None:
        wrote = False
        try:
            while True:
                line = state["log_q"].get_nowait()
                if not wrote:
                    logbox.configure(state="normal")
                    wrote = True
                logbox.insert("end", line)
        except queue.Empty:
            pass
        if wrote:
            # Trim to keep the widget light.
            n = int(logbox.index("end-1c").split(".")[0])
            if n > MAX_LINES:
                logbox.delete("1.0", f"{n - MAX_LINES}.0")
            logbox.see("end")
            logbox.configure(state="disabled")

    def _set_status(running: bool, external: bool = False) -> None:
        if running:
            dot.itemconfig(dot_id, fill=GREEN)
            status_lbl.config(text="Running (external)" if external else "Running")
            port = port_var.get()
            host = "0.0.0.0" if net_var.get() else "localhost"
            url_lbl.config(text=f"http://{host}:{port}")
            b_start.config(state="disabled")
            b_stop.config(state="normal")
        else:
            dot.itemconfig(dot_id, fill=MUTED)
            status_lbl.config(text="Stopped")
            url_lbl.config(text="")
            b_start.config(state="normal")
            b_stop.config(state="disabled")

    def tick() -> None:
        _drain_log()
        proc = state["proc"]
        if proc is not None and proc.poll() is None:
            _set_status(True)
        else:
            if proc is not None and proc.poll() is not None:
                log(f"── server exited (code {proc.poll()}) ──")
                state["proc"] = None
            # Detect a server we didn't start (orphan / external run.py).
            port = int(port_var.get()) if port_var.get().isdigit() else DEFAULT_PORT
            if pid_on_port(port):
                _set_status(True, external=True)
            else:
                _set_status(False)
        root.after(1000, tick)

    def on_close() -> None:
        proc = state["proc"]
        running = (proc is not None and proc.poll() is None) or pid_on_port(
            int(port_var.get()) if port_var.get().isdigit() else DEFAULT_PORT)
        if running:
            ans = messagebox.askyesnocancel(
                "Quit launcher",
                "TradeAgent is running.\n\n"
                "Yes  — stop the server and quit\n"
                "No   — leave it running and quit\n"
                "Cancel — keep the launcher open")
            if ans is None:
                return
            if ans:
                do_stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    _set_status(False)
    log("TradeAgent Launcher ready. Press ▶ Start.")
    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
