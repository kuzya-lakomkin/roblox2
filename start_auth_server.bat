@echo off
cd /d "%~dp0"
echo === SWAGA Auth-сервер (порт 50008) ===
python -m auth_server.server
pause
