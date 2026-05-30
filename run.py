import subprocess
import sys
import time
import signal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

# Python из виртуального окружения (если есть), иначе текущий
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"  # Windows
if not VENV_PYTHON.exists():
    VENV_PYTHON = BASE_DIR / ".venv" / "bin" / "python"  # Linux/Mac
if not VENV_PYTHON.exists():
    VENV_PYTHON = sys.executable  # fallback

# npm: на Windows нужен shell=True
IS_WINDOWS = sys.platform == "win32"


def start_process(args: list, cwd=BASE_DIR, shell=False) -> subprocess.Popen:
    return subprocess.Popen(
        args,
        cwd=cwd,
        stdout=sys.stdout,
        stderr=sys.stderr,
        shell=shell,
    )


def main():
    processes = {}

    # ── 1. API (FastAPI / uvicorn) ────────────────────────────────────────────
    print("[run] Starting API...")
    processes["api"] = start_process(
        [
            str(VENV_PYTHON),
            "-m",
            "uvicorn",
            "src.main:app",
            "--reload",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ]
    )

    # Даём uvicorn подняться перед запуском бота
    time.sleep(2)

    # ── 2. Telegram bot ───────────────────────────────────────────────────────
    print("[run] Starting Telegram bot...")
    processes["bot"] = start_process(
        [
            str(VENV_PYTHON),
            "-m",
            "src.bot.runner",
        ]
    )

    # ── 3. Frontend (Vite dev-server) ─────────────────────────────────────────
    if FRONTEND_DIR.is_dir():
        print("[run] Starting frontend (npm run dev)...")
        npm_cmd = ["npm.cmd", "run", "dev"] if IS_WINDOWS else ["npm", "run", "dev"]
        processes["frontend"] = start_process(
            npm_cmd,
            cwd=FRONTEND_DIR,
            shell=IS_WINDOWS,
        )
    else:
        print(f"[run] Frontend dir not found ({FRONTEND_DIR}), skipping.")

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
                print(f"[run]   killing {name} (pid={p.pid})")
                p.kill()

        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("[run] All services started. Press Ctrl+C to stop.")

    # Держим процесс живым; перезапускаем упавшие дочерние процессы
    while True:
        time.sleep(2)
        for name, p in list(processes.items()):
            if p.poll() is not None:
                print(
                    f"[run] WARNING: '{name}' exited with code {p.returncode}, restarting..."
                )
                # Перезапускаем ту же команду через args
                processes[name] = subprocess.Popen(
                    p.args,
                    cwd=p.cwd if hasattr(p, "cwd") else BASE_DIR,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                )


if __name__ == "__main__":
    main()
