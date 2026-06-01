import subprocess
import sys
import time
import signal
from pathlib import Path

# ── Пути ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

# ── Окружение ─────────────────────────────────────────────────────────────────
IS_WINDOWS = sys.platform == "win32"
IS_PROD = not IS_WINDOWS  # На Render всегда Linux


# ── Python-интерпретатор ──────────────────────────────────────────────────────
def _find_python() -> Path:
    for candidate in [
        BASE_DIR / ".venv" / "Scripts" / "python.exe",  # Windows venv
        BASE_DIR / ".venv" / "bin" / "python",  # Linux/Mac venv
    ]:
        if candidate.exists():
            return candidate
    return Path(sys.executable)  # fallback — системный Python


VENV_PYTHON = _find_python()


# ── Управление процессами ─────────────────────────────────────────────────────
class ManagedProcess:
    """Обёртка над Popen с сохранением метаданных для перезапуска."""

    def __init__(self, name: str, args: list, cwd: Path = BASE_DIR):
        self.name = name
        self.args = args
        self.cwd = cwd
        self._proc: subprocess.Popen | None = None
        self.restart_count = 0

    def start(self) -> None:
        self._proc = subprocess.Popen(
            self.args,
            cwd=self.cwd,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        print(f"[run] Started '{self.name}' (pid={self._proc.pid})", flush=True)

    def restart(self) -> None:
        self.restart_count += 1
        print(
            f"[run] Restarting '{self.name}' "
            f"(attempt #{self.restart_count}, last code={self._proc.returncode})..."
        )
        self.start()

    def stop(self, timeout: int = 10) -> None:
        if self._proc is None or self._proc.poll() is not None:
            return
        print(f"[run]   terminating '{self.name}' (pid={self._proc.pid})")
        self._proc.terminate()
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"[run]   killing '{self.name}' (pid={self._proc.pid})")
            self._proc.kill()

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def exited(self) -> bool:
        return self._proc is not None and self._proc.poll() is not None


# ── Определение сервисов ──────────────────────────────────────────────────────
def build_services() -> list[ManagedProcess]:
    services = []

    # 1. API (FastAPI / uvicorn)
    services.append(
        ManagedProcess(
            name="api",
            args=[
                str(VENV_PYTHON),
                "-m",
                "uvicorn",
                "src.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8000",
                *(["--reload"] if not IS_PROD else []),
            ],
        )
    )

    # 2. Telegram bot
    services.append(
        ManagedProcess(
            name="bot",
            args=[str(VENV_PYTHON), "-m", "src.bot.runner"],
        )
    )

    # 3. Vite dev-сервер — только локально
    if FRONTEND_DIR.is_dir() and not IS_PROD:
        npm_cmd = ["npm.cmd", "run", "dev"] if IS_WINDOWS else ["npm", "run", "dev"]
        services.append(
            ManagedProcess(
                name="frontend",
                args=npm_cmd,
                cwd=FRONTEND_DIR,
            )
        )

    return services


# ── Точка входа ───────────────────────────────────────────────────────────────
def main() -> None:
    services = build_services()

    # Запуск всех сервисов
    for svc in services:
        svc.start()
        if svc.name == "api":
            time.sleep(2)  # Даём uvicorn подняться перед запуском бота

    # Graceful shutdown
    def shutdown(*_):
        print("\n[run] Shutting down all services...")
        for svc in services:
            svc.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print("[run] All services started. Press Ctrl+C to stop.")

    # Мониторинг и перезапуск упавших процессов
    MAX_RESTARTS = 10

    while True:
        time.sleep(2)
        for svc in services:
            if svc.exited:
                print(
                    f"[run] '{svc.name}' exited with code {svc._proc.returncode}",
                    flush=True,
                )
                if svc.restart_count >= MAX_RESTARTS:
                    print(
                        f"[run] ERROR: '{svc.name}' exceeded {MAX_RESTARTS} restarts."
                    )
                    shutdown()
                svc.restart()


if __name__ == "__main__":
    main()
