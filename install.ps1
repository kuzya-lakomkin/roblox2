$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "SWAGA Installer"

# ---- настройки ----
$REPO_URL    = "https://github.com/kuzya-lakomkin/roblox2.git"
$INSTALL_DIR = "$env:LOCALAPPDATA\SWAGA"
$SHORTCUT    = [Environment]::GetFolderPath("Desktop") + "\SWAGA.lnk"
# -------------------

Write-Host ""
Write-Host " === SWAGA - Установка ===" -ForegroundColor Cyan
Write-Host ""

# ---------- утилиты ----------
function Refresh-Path {
    $u = [Environment]::GetEnvironmentVariable("PATH", "User")
    $s = [Environment]::GetEnvironmentVariable("PATH", "Machine")
    if (-not $u) { $u = "" }
    if (-not $s) { $s = "" }
    $env:PATH = "$u;$s"
}

function Find-Exe($name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Check-PythonVersion($pyExe) {
    try {
        $v = & $pyExe -c "import sys; print(sys.version_info.major, sys.version_info.minor)" 2>$null
        if ($v) {
            $p = $v.Trim().Split(" ")
            $maj = [int]$p[0]; $min = [int]$p[1]
            return ($maj -gt 3 -or ($maj -eq 3 -and $min -ge 11))
        }
    } catch {}
    return $false
}

# ---------- 1. Python 3.11+ ----------
Write-Host "[1/5] Проверка Python..." -ForegroundColor Yellow
Refresh-Path
$pyExe = Find-Exe "python"

$pyOk = $false
if ($pyExe) { $pyOk = Check-PythonVersion $pyExe }

if (-not $pyOk) {
    Write-Host "    Python 3.11+ не найден. Устанавливаю через winget..." -ForegroundColor Yellow
    try {
        & winget install --id Python.Python.3.11 -e --silent `
            --accept-source-agreements --accept-package-agreements 2>$null
    } catch {}
    Refresh-Path
    $pyExe = Find-Exe "python"
    if (-not $pyExe -or -not (Check-PythonVersion $pyExe)) {
        # fallback: прямая загрузка
        $setup = "$env:TEMP\py_setup.exe"
        Write-Host "    winget не справился, качаю с python.org..." -ForegroundColor Yellow
        try {
            Invoke-WebRequest "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" `
                -OutFile $setup -UseBasicParsing
            & $setup /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
            Remove-Item $setup -Force -ErrorAction SilentlyContinue
        } catch {
            Write-Host "[ОШИБКА] Не удалось установить Python. Установи вручную: python.org/downloads" -ForegroundColor Red
            Read-Host "Нажми Enter для выхода"
            exit 1
        }
        Refresh-Path
        $pyExe = Find-Exe "python"
    }
}
if (-not $pyExe) {
    Write-Host "[ОШИБКА] Python не найден после установки. Перезапусти инсталлятор." -ForegroundColor Red
    Read-Host "Нажми Enter для выхода"
    exit 1
}
Write-Host "[OK] Python: $pyExe" -ForegroundColor Green

# ---------- 2. Git ----------
Write-Host "[2/5] Проверка Git..." -ForegroundColor Yellow
Refresh-Path
$gitExe = Find-Exe "git"

if (-not $gitExe) {
    Write-Host "    Git не найден. Устанавливаю через winget..." -ForegroundColor Yellow
    try {
        & winget install --id Git.Git -e --silent `
            --accept-source-agreements --accept-package-agreements 2>$null
    } catch {}
    Refresh-Path
    $gitExe = Find-Exe "git"
    if (-not $gitExe) {
        # попробовать стандартный путь
        $candidates = @(
            "C:\Program Files\Git\bin\git.exe",
            "C:\Program Files (x86)\Git\bin\git.exe"
        )
        foreach ($c in $candidates) {
            if (Test-Path $c) { $gitExe = $c; break }
        }
    }
}
if (-not $gitExe) {
    Write-Host "[ОШИБКА] Git не найден. Установи вручную: git-scm.com, затем перезапусти инсталлятор." -ForegroundColor Red
    Read-Host "Нажми Enter для выхода"
    exit 1
}
Write-Host "[OK] Git: $gitExe" -ForegroundColor Green

# ---------- 3. Клонировать/обновить репозиторий ----------
Write-Host "[3/5] Загрузка файлов игры..." -ForegroundColor Yellow

if (Test-Path (Join-Path $INSTALL_DIR ".git")) {
    Write-Host "    Папка существует - обновляю (git pull)..." -ForegroundColor Gray
    & $gitExe -C $INSTALL_DIR pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    [!] git pull не удался - продолжаю с текущими файлами." -ForegroundColor Yellow
    } else {
        Write-Host "[OK] Обновлено." -ForegroundColor Green
    }
} else {
    if (Test-Path $INSTALL_DIR) {
        Remove-Item $INSTALL_DIR -Recurse -Force
    }
    Write-Host "    Клонирую $REPO_URL в $INSTALL_DIR ..." -ForegroundColor Gray
    & $gitExe clone $REPO_URL $INSTALL_DIR
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ОШИБКА] git clone завершился с ошибкой." -ForegroundColor Red
        Read-Host "Нажми Enter для выхода"
        exit 1
    }
    Write-Host "[OK] Репозиторий клонирован." -ForegroundColor Green
}

# ---------- 4. Зависимости ----------
Write-Host "[4/5] Установка зависимостей..." -ForegroundColor Yellow
& $pyExe -m pip install --upgrade pip --quiet 2>$null
$reqFile = Join-Path $INSTALL_DIR "requirements.txt"
if (Test-Path $reqFile) {
    & $pyExe -m pip install -r $reqFile --quiet
} else {
    & $pyExe -m pip install panda3d panda3d-gltf --quiet
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ОШИБКА] pip install завершился с ошибкой." -ForegroundColor Red
    Read-Host "Нажми Enter для выхода"
    exit 1
}
Write-Host "[OK] Зависимости установлены." -ForegroundColor Green

# ---------- 5. Ярлык на рабочем столе ----------
Write-Host "[5/5] Создание ярлыка..." -ForegroundColor Yellow
try {
    $pythonwExe = Join-Path (Split-Path $pyExe) "pythonw.exe"
    if (-not (Test-Path $pythonwExe)) { $pythonwExe = $pyExe }

    $updaterScript = Join-Path $INSTALL_DIR "launch_updater.pyw"
    $iconPath      = Join-Path $INSTALL_DIR "assets\swaga.ico"

    $ws  = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($SHORTCUT)
    $lnk.TargetPath       = $pythonwExe
    $lnk.Arguments        = "`"$updaterScript`""
    $lnk.WorkingDirectory = $INSTALL_DIR
    $lnk.Description      = "SWAGA"
    if (Test-Path $iconPath) { $lnk.IconLocation = "$iconPath,0" }
    $lnk.Save()
    Write-Host "[OK] Ярлык создан на рабочем столе." -ForegroundColor Green
} catch {
    Write-Host "[!] Ярлык не создан: $_" -ForegroundColor Yellow
    Write-Host "    Запускай вручную: pythonw `"$INSTALL_DIR\launch_updater.pyw`""
}

# ---------- готово ----------
Write-Host ""
Write-Host " === Установка завершена! ===" -ForegroundColor Cyan
Write-Host " Запускай SWAGA с рабочего стола." -ForegroundColor White
Write-Host " Обновления будут загружаться автоматически при каждом запуске." -ForegroundColor Gray
Write-Host ""
Read-Host "Нажми Enter для выхода"
