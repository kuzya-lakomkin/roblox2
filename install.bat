@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title SWAGA - Установщик

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║            SWAGA  —  Установка игры             ║
echo  ╚══════════════════════════════════════════════════╝
echo.

:: ─── 1. Проверить Python 3.11+ ───────────────────────────────────────────
set PY_OK=0
python --version >nul 2>&1
if %errorlevel% equ 0 (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
    for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
        if %%a geq 3 if %%b geq 11 set PY_OK=1
    )
)

if !PY_OK! equ 0 (
    echo [!] Python 3.11+ не найден. Пробую winget...
    winget install --id Python.Python.3.11 -e --silent ^
          --accept-source-agreements --accept-package-agreements 2>nul
    if !errorlevel! neq 0 (
        echo [!] winget не сработал. Скачиваю Python с официального сайта...
        powershell -NoProfile -Command ^
            "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%TEMP%\py_setup.exe' -UseBasicParsing"
        if not exist "%TEMP%\py_setup.exe" (
            echo [ОШИБКА] Не удалось скачать Python. Установите вручную: python.org/downloads
            pause & exit /b 1
        )
        echo [*] Запускаю установщик Python (тихая установка)...
        "%TEMP%\py_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
        del "%TEMP%\py_setup.exe" 2>nul
        :: обновить PATH в текущей сессии
        for /f "tokens=*" %%p in ('powershell -NoProfile -Command ^
            "[Environment]::GetEnvironmentVariable(\"PATH\",\"User\")"') do ^
            set PATH=%%p;%PATH%
    )
    echo [OK] Python установлен.
) else (
    echo [OK] Python !PYVER! уже установлен.
)

:: ─── 2. Убедиться что pip доступен ──────────────────────────────────────
echo.
echo [*] Обновляю pip...
python -m pip install --upgrade pip --quiet
if %errorlevel% neq 0 (
    echo [!] pip недоступен — попробую python -m ensurepip
    python -m ensurepip --upgrade --quiet
)

:: ─── 3. Зависимости клиента ─────────────────────────────────────────────
echo [*] Устанавливаю зависимости игры (panda3d, panda3d-gltf)...
python -m pip install panda3d panda3d-gltf --quiet
if %errorlevel% neq 0 (
    echo.
    echo [ОШИБКА] Не удалось установить зависимости.
    echo Запустите вручную: python -m pip install panda3d panda3d-gltf
    pause & exit /b 1
)
echo [OK] Зависимости установлены.

:: ─── 4. Создать ярлык на рабочем столе ──────────────────────────────────
echo.
echo [*] Создаю ярлык SWAGA на рабочем столе...
set "GDIR=%~dp0"
set "GDIR=!GDIR:~0,-1!"

powershell -NoProfile -Command ^
  "$ws=New-Object -ComObject WScript.Shell;" ^
  "$lnk=$ws.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\SWAGA.lnk');" ^
  "$lnk.TargetPath='pythonw.exe';" ^
  "$lnk.Arguments='launcher.pyw';" ^
  "$lnk.WorkingDirectory='!GDIR!';" ^
  "$lnk.Description='SWAGA Game';" ^
  "$lnk.Save()"

if %errorlevel% equ 0 (
    echo [OK] Ярлык SWAGA создан на рабочем столе.
) else (
    echo [!] Ярлык не создан — запускайте вручную: python launcher.pyw
)

:: ─── 5. Итог ─────────────────────────────────────────────────────────────
echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║   Установка завершена!                          ║
echo  ║   Запускайте SWAGA с ярлыка на рабочем столе.  ║
echo  ╚══════════════════════════════════════════════════╝
echo.
pause
