import subprocess
import sys
import time
import signal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

IS_PROD = sys.platform != "win32"  # На Render всегда Linux

VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = BASE_DIR / ".venv" / "bin" / "python"
if not VENV_PYTHON.exists():
    VENV_PYTHON = sys.executable


def start_process(args: list, cwd=None) -> subprocess.Popen:
    p = subprocess.Popen(
        args,
        cwd=cwd or BASE_DIR,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )
    p._cwd = cwd or BASE_DIR  # сохраняем вручную для перезапуска
    p._args = args
    return p


def main():
    processes = {}

    # ── 1. API (FastAPI / uvicorn) ────────────────────────────────────────────
    print("[run] Starting API...")
    processes["api"] = start_process(
        [
            str(VENV_PYTHON), "-m", "uvicorn",
            "src.main:app",
            "--host", "0.0.0.0",   # важно для Render
            "--port", "8000",
            # без --reload на проде
        ]
    )

    time.sleep(2)

    # ── 2. Telegram bot ───────────────────────────────────────────────────────
    print("[run] Starting Telegram bot...")
    processes["bot"] = start_process(
        [str(VENV_PYTHON), "-m", "src.bot.runner"]
    )

    # ── 3. Frontend — только локально ────────────────────────────────────────
    if FRONTEND_DIR.is_dir() and not IS_PROD:
        print("[run] Starting frontend (npm run dev)...")
        npm_cmd = ["npm.cmd", "run", "dev"]
        processes["frontend"] = start_process(npm_cmd, cwd=FRONTEND_DIR)
    else:
        print("[run] Skipping frontend dev-server (prod or dir not found).")

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    def shutdown(*_):
        print("\n[run] Stopping all services...")
        for name, p in processes.items():
            if p.poll() is None:
                print(f"[run]   terminating {name} (pid={p.pid})")
                p.terminate()
        for name, p in processes.items():
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("[run] All services started. Press Ctrl+C to stop.")

    while True:
        time.sleep(2)
        for name, p in list(processes.items()):
            if p.poll() is not None:
                print(f"[run] WARNING: '{name}' exited (code {p.returncode}), restarting...")
                processes[name] = start_process(p._args, cwd=p._cwd)


if __name__ == "__main__":
    main()
