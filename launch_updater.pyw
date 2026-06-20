"""
Запускается по иконке вместо launcher.pyw.
1. Тихо делает git pull (если Git установлен).
2. Запускает launcher.pyw через pythonw (без консоли).
"""
import subprocess
import sys
import os

_DIR = os.path.dirname(os.path.abspath(__file__))

# --- git pull (тихо, не блокирует запуск при отсутствии сети) ---
try:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW
    subprocess.run(
        ["git", "pull", "--ff-only", "--quiet"],
        cwd=_DIR,
        timeout=15,
        creationflags=flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
except Exception:
    pass  # нет git, нет сети — не беда

# --- запуск игры ---
pythonw = sys.executable
if os.path.basename(pythonw).lower() == "python.exe":
    candidate = os.path.join(os.path.dirname(pythonw), "pythonw.exe")
    if os.path.exists(candidate):
        pythonw = candidate

subprocess.Popen(
    [pythonw, os.path.join(_DIR, "launcher.pyw")],
    cwd=_DIR,
)
