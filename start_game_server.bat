@echo off
cd /d "%~dp0"
echo === SWAGA Игровой сервер (порт 50007) ===
python -m server.server
pause
