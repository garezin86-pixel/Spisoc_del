import subprocess
import sys
import time
import signal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def start_process(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        args,
        cwd=BASE_DIR,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def main():
    api_process = start_process(
        [
            sys.executable,
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

    time.sleep(2)

    bot_process = start_process(
        [
            sys.executable,
            "-m",
            "src.bot.runner",
        ]
    )

    def shutdown(*_):
        print("\nStopping services...")

        for p in (bot_process, api_process):
            if p.poll() is None:
                p.terminate()

        for p in (bot_process, api_process):
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()

        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # просто держим процесс живым
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()


# import subprocess
# import os
# import time
# import logging


# # Убираем WinError 10054 из логов
# class FilterConnectionReset(logging.Filter):
#     def filter(self, record):
#         return (
#             "WinError 10054" not in record.getMessage()
#             and "ConnectionResetError" not in record.getMessage()
#             and "ConnectionDoesNotExistError" not in record.getMessage()
# )


# logging.getLogger("uvicorn.error").addFilter(FilterConnectionReset())

# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# frontend_dir = os.path.join(BASE_DIR, "frontend")

# # Python из виртуального окружения
# VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")  # Windows
# if not os.path.exists(VENV_PYTHON):
#     VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "bin", "python")  # Linux/Mac

# # ── Backend ───────────────────────────────────────────────────────────────────
# backend_process = subprocess.Popen(
#     [
#         VENV_PYTHON,
#         "-m",
#         "uvicorn",
#         "src.main:app",
#         "--reload",
#         "--host",
#         "127.0.0.1",
#         "--port",
#         "8000",
#     ],
#     cwd=BASE_DIR,
# )

# time.sleep(2)

# # ── Frontend (только если папка существует) ───────────────────────────────────
# frontend_process = None
# if os.path.isdir(frontend_dir):
#     frontend_process = subprocess.Popen(
#         ["npm", "run", "dev"],
#         cwd=frontend_dir,
#         shell=True,
#     )

# try:
#     backend_process.wait()
#     if frontend_process:
#         frontend_process.wait()
# except KeyboardInterrupt:
#     print("\n🔄 Завершение...")
#     backend_process.terminate()
#     if frontend_process:
#         frontend_process.terminate()
