$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "SWAGA Installer"

Write-Host ""
Write-Host " === SWAGA - Installation ===" -ForegroundColor Cyan
Write-Host ""

# Обновить PATH текущей сессии из реестра (на случай если Python уже установлен, но не в PATH)
function Refresh-Path {
    $user   = [Environment]::GetEnvironmentVariable("PATH", "User")   ?? ""
    $system = [Environment]::GetEnvironmentVariable("PATH", "Machine") ?? ""
    $env:PATH = "$user;$system"
}

# Найти python.exe — возвращает путь или $null
function Find-Python {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    # Стандартные места установки для текущего пользователя
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Program Files\Python311\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

# Проверить версию python по пути
function Check-Version($pyExe) {
    try {
        $v = & $pyExe -c "import sys; print(sys.version_info.major, sys.version_info.minor)" 2>$null
        if ($v) {
            $parts = $v.Trim().Split(" ")
            $major = [int]$parts[0]; $minor = [int]$parts[1]
            return ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11))
        }
    } catch {}
    return $false
}

# --- 1. Check / Install Python 3.11+ ---
Refresh-Path
$pyExe = Find-Python

if ($pyExe -and (Check-Version $pyExe)) {
    Write-Host "[OK] Python found: $pyExe" -ForegroundColor Green
} else {
    Write-Host "[!] Python 3.11+ not found. Trying winget..." -ForegroundColor Yellow
    $installed = $false

    try {
        & winget install --id Python.Python.3.11 -e --silent `
            --accept-source-agreements --accept-package-agreements 2>$null
        if ($LASTEXITCODE -eq 0) { $installed = $true }
    } catch {}

    if (-not $installed) {
        Write-Host "[!] winget failed. Downloading from python.org..." -ForegroundColor Yellow
        $pySetup = "$env:TEMP\py_setup.exe"
        try {
            Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" `
                -OutFile $pySetup -UseBasicParsing
        } catch {
            Write-Host "[ERROR] Could not download Python. Install manually: python.org/downloads" -ForegroundColor Red
            Read-Host "Press Enter to exit"
            exit 1
        }
        Write-Host "[*] Running Python installer..."
        & $pySetup /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
        Remove-Item $pySetup -Force -ErrorAction SilentlyContinue
    }

    # Обновить PATH после любого способа установки
    Refresh-Path
    $pyExe = Find-Python

    if (-not $pyExe) {
        Write-Host "[ERROR] Python still not found after install. Please restart and run again." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[OK] Python installed: $pyExe" -ForegroundColor Green
}

# --- 2. Git update (если git установлен) ---
Write-Host ""
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if ($gitCmd) {
    $gameDir2 = Split-Path -Parent (Resolve-Path "$PSScriptRoot\launcher.pyw")
    $isRepo = Test-Path (Join-Path $gameDir2 ".git")
    if ($isRepo) {
        Write-Host "[*] Checking for updates (git pull)..."
        try {
            $result = & git -C $gameDir2 pull --ff-only 2>&1
            if ($LASTEXITCODE -eq 0) {
                if ($result -match "Already up to date") {
                    Write-Host "[OK] Game is up to date." -ForegroundColor Green
                } else {
                    Write-Host "[OK] Updated: $result" -ForegroundColor Green
                }
            } else {
                Write-Host "[!] git pull failed (local changes?): $result" -ForegroundColor Yellow
            }
        } catch {
            Write-Host "[!] git update skipped: $_" -ForegroundColor Yellow
        }
    } else {
        Write-Host "[i] Not a git repo, skipping update check." -ForegroundColor Gray
    }
} else {
    Write-Host "[i] git not found, skipping update check." -ForegroundColor Gray
}

# --- 3. Upgrade pip ---
Write-Host ""
Write-Host "[*] Upgrading pip..."
& $pyExe -m pip install --upgrade pip --quiet 2>$null

# --- 4. Install game dependencies ---
Write-Host "[*] Installing panda3d and panda3d-gltf (may take a minute)..."
& $pyExe -m pip install panda3d panda3d-gltf --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Failed to install dependencies." -ForegroundColor Red
    Write-Host "Run manually: python -m pip install panda3d panda3d-gltf"
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK] Dependencies installed." -ForegroundColor Green

# --- 5. Create desktop shortcut ---
Write-Host ""
Write-Host "[*] Creating desktop shortcut..."
try {
    $pythonwExe = Join-Path (Split-Path $pyExe) "pythonw.exe"
    if (-not (Test-Path $pythonwExe)) { $pythonwExe = $pyExe }

    $gameDir = Split-Path -Parent (Resolve-Path "$PSScriptRoot\launcher.pyw")
    $iconPath = Join-Path $gameDir "assets\swaga.ico"

    $ws  = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut([Environment]::GetFolderPath("Desktop") + "\SWAGA.lnk")
    $lnk.TargetPath       = $pythonwExe
    $lnk.Arguments        = "`"$gameDir\launcher.pyw`""
    $lnk.WorkingDirectory = $gameDir
    $lnk.Description      = "SWAGA Game"
    if (Test-Path $iconPath) {
        $lnk.IconLocation = "$iconPath,0"
    }
    $lnk.Save()
    Write-Host "[OK] Shortcut created on Desktop." -ForegroundColor Green
} catch {
    Write-Host "[!] Shortcut not created: $_" -ForegroundColor Yellow
    Write-Host "    Run manually: python launcher.pyw"
}

# --- Done ---
Write-Host ""
Write-Host " === Installation complete! ===" -ForegroundColor Cyan
Write-Host " Launch SWAGA from the Desktop shortcut."
Write-Host ""
