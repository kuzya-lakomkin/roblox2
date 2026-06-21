$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "SWAGA Installer"

# ---- settings ----
$REPO_URL    = "https://github.com/kuzya-lakomkin/roblox2.git"
$INSTALL_DIR = "$env:LOCALAPPDATA\SWAGA"
$SHORTCUT    = [Environment]::GetFolderPath("Desktop") + "\SWAGA.lnk"
# ------------------

Write-Host ""
Write-Host " === SWAGA Installer ===" -ForegroundColor Cyan
Write-Host ""

# ---------- helpers ----------
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

function Check-Python($pyExe) {
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
Write-Host "[1/5] Checking Python..." -ForegroundColor Yellow
Refresh-Path
$pyExe = Find-Exe "python"
$pyOk = $false
if ($pyExe) { $pyOk = Check-Python $pyExe }

if (-not $pyOk) {
    Write-Host "      Python 3.11+ not found. Trying winget..." -ForegroundColor Yellow
    try {
        & winget install --id Python.Python.3.11 -e --silent --accept-source-agreements --accept-package-agreements
    } catch {}
    Refresh-Path
    $pyExe = Find-Exe "python"
    if (-not $pyExe -or -not (Check-Python $pyExe)) {
        $setup = "$env:TEMP\py_setup.exe"
        Write-Host "      Downloading from python.org..." -ForegroundColor Yellow
        try {
            Invoke-WebRequest "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $setup -UseBasicParsing
            & $setup /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
            Remove-Item $setup -Force -ErrorAction SilentlyContinue
        } catch {
            Write-Host "[ERROR] Cannot install Python. Install manually: python.org/downloads" -ForegroundColor Red
            Read-Host "Press Enter to exit"
            exit 1
        }
        Refresh-Path
        $pyExe = Find-Exe "python"
    }
}
if (-not $pyExe) {
    Write-Host ""
    Write-Host "[!]    Python was just installed but requires a reboot to activate." -ForegroundColor Yellow
    Write-Host "       Please REBOOT your PC and run the installer again." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK]   Python: $pyExe" -ForegroundColor Green

# ---------- 2. Git ----------
Write-Host "[2/5] Checking Git..." -ForegroundColor Yellow
Refresh-Path
$gitExe = Find-Exe "git"

if (-not $gitExe) {
    Write-Host "      Git not found. Trying winget..." -ForegroundColor Yellow
    try {
        & winget install --id Git.Git -e --silent --accept-source-agreements --accept-package-agreements
    } catch {}
    Refresh-Path
    $gitExe = Find-Exe "git"
    if (-not $gitExe) {
        foreach ($c in @("C:\Program Files\Git\bin\git.exe", "C:\Program Files (x86)\Git\bin\git.exe")) {
            if (Test-Path $c) { $gitExe = $c; break }
        }
    }
}
if (-not $gitExe) {
    # Git был только что установлен winget-ом, но PATH ещё не обновился в текущей сессии
    $justInstalled = Test-Path "C:\Program Files\Git\bin\git.exe"
    if ($justInstalled) {
        Write-Host ""
        Write-Host "[!]    Git was just installed but requires a reboot to activate." -ForegroundColor Yellow
        Write-Host "       Please REBOOT your PC and run the installer again." -ForegroundColor Yellow
        Write-Host ""
    } else {
        Write-Host "[ERROR] Git not found. Install manually: git-scm.com, then re-run this installer." -ForegroundColor Red
    }
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK]   Git: $gitExe" -ForegroundColor Green

# ---------- 3. Clone / update repository ----------
Write-Host "[3/5] Downloading game files..." -ForegroundColor Yellow

# Force HTTPS even if user git config has SSH insteadOf rules
$gitHttps = @("-c", "url.$REPO_URL.insteadOf=$REPO_URL")

$gitDir = Join-Path $INSTALL_DIR ".git"
if (Test-Path $gitDir) {
    Write-Host "      Folder exists - running git pull..." -ForegroundColor Gray
    & $gitExe @gitHttps -C $INSTALL_DIR pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Write-Host "      [!] git pull failed - continuing with existing files." -ForegroundColor Yellow
    } else {
        Write-Host "[OK]   Updated." -ForegroundColor Green
    }
} else {
    if (Test-Path $INSTALL_DIR) {
        Remove-Item $INSTALL_DIR -Recurse -Force
    }
    Write-Host "      Cloning $REPO_URL to $INSTALL_DIR ..." -ForegroundColor Gray
    & $gitExe @gitHttps clone $REPO_URL $INSTALL_DIR
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] git clone failed." -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[OK]   Repository cloned." -ForegroundColor Green
}

# ---------- 4. Dependencies ----------
Write-Host "[4/5] Installing dependencies..." -ForegroundColor Yellow

# pip may not be in PATH right after Python install - call via python -m pip
$pipTest = & $pyExe -m pip --version 2>&1
if ($LASTEXITCODE -ne 0 -or $pipTest -notmatch "pip") {
    Write-Host ""
    Write-Host "[ERROR] pip not found or not accessible." -ForegroundColor Red
    Write-Host "        Please REBOOT your PC and run the installer again." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

& $pyExe -m pip install --upgrade pip --quiet
$reqFile = Join-Path $INSTALL_DIR "requirements.txt"
if (Test-Path $reqFile) {
    & $pyExe -m pip install -r $reqFile --quiet
} else {
    & $pyExe -m pip install panda3d panda3d-gltf --quiet
}
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] pip install failed." -ForegroundColor Red
    Write-Host "        If the error mentions pip or PATH - please REBOOT and run installer again." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK]   Dependencies installed." -ForegroundColor Green

# ---------- 5. Desktop shortcut ----------
Write-Host "[5/5] Creating shortcut..." -ForegroundColor Yellow
try {
    $pythonwExe = Join-Path (Split-Path $pyExe) "pythonw.exe"
    if (-not (Test-Path $pythonwExe)) { $pythonwExe = $pyExe }

    $updater  = Join-Path $INSTALL_DIR "launch_updater.pyw"
    $iconPath = Join-Path $INSTALL_DIR "assets\swaga.ico"

    $ws  = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($SHORTCUT)
    $lnk.TargetPath       = $pythonwExe
    $lnk.Arguments        = "`"$updater`""
    $lnk.WorkingDirectory = $INSTALL_DIR
    $lnk.Description      = "SWAGA"
    if (Test-Path $iconPath) { $lnk.IconLocation = "$iconPath,0" }
    $lnk.Save()
    Write-Host "[OK]   Desktop shortcut created." -ForegroundColor Green
} catch {
    Write-Host "[!]   Shortcut not created: $_" -ForegroundColor Yellow
    Write-Host "       Run manually: pythonw `"$INSTALL_DIR\launch_updater.pyw`""
}

# ---------- done ----------
Write-Host ""
Write-Host " === Installation complete! ===" -ForegroundColor Cyan
Write-Host " Launch SWAGA from the Desktop shortcut." -ForegroundColor White
Write-Host " Updates download automatically on each launch." -ForegroundColor Gray
Write-Host ""
Read-Host "Press Enter to exit"
