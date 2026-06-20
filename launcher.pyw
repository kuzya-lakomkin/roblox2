"""Запускает SWAGA двойным кликом — без консоли (pythonw.exe)."""
import os
import sys
import subprocess

here = os.path.dirname(os.path.abspath(__file__))
subprocess.Popen([sys.executable, "-m", "client.main"], cwd=here)
