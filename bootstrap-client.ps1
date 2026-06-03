# bootstrap-client.ps1 — install the hermes-voice Python client (mic side) on Windows.
#
# Use this on the machine that CAPTURES the microphone (often a different
# box from the one running the gateway + Whisper GPU). Installs:
#   - Python venv (reused if present)
#   - sounddevice, numpy, websockets, miniaudio, python-dotenv
#   - .env with HERMES_VOICE_WS_HOST / HERMES_VOICE_WS_PORT / GROQ_API_KEY
#
# Does NOT install: Whisper, ctranslate2, fastapi, Edge TTS — those are
# gateway-side and live in requirements-whisper.txt / requirements-web.txt.
#
# Requirements: PowerShell 5.1+ (ships with Windows 10/11), Python 3.10+.
#
# Usage:
#   .\bootstrap-client.ps1                       # prompts for gateway host/port
#   .\bootstrap-client.ps1 192.168.1.3 7979      # non-interactive
#   powershell -ExecutionPolicy Bypass -File bootstrap-client.ps1 192.168.1.3 7979
#
# If running from a fresh PowerShell that blocks scripts, use the
# -ExecutionPolicy Bypass form above, or run once as admin:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

[CmdletBinding()]
param(
    [string]$GatewayHost = "",
    [string]$GatewayPort = ""
)

$ErrorActionPreference = "Stop"

# ── Color helpers ────────────────────────────────────────────────────────────
function Info($msg)  { Write-Host "[bootstrap] $msg" -ForegroundColor Blue }
function Ok($msg)    { Write-Host "[bootstrap] $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "[bootstrap] $msg" -ForegroundColor Yellow }
function Err($msg)   { Write-Host "[bootstrap] $msg" -ForegroundColor Red }
function Die($msg)   { Err $msg; exit 1 }

# ── Find repo root (this script lives in the repo) ───────────────────────────
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
}
Set-Location $ScriptDir
Info "Repo root: $ScriptDir"

# ── Python 3.10+ check ───────────────────────────────────────────────────────
# Try `py -3` launcher first (Windows standard), fall back to `python`.
$pythonCmd = $null
foreach ($candidate in @("py", "python", "python3")) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        # For `py`, ensure it can find 3.10+
        if ($candidate -eq "py") {
            $ver = & py -3 --version 2>&1
            if ($LASTEXITCODE -eq 0) { $pythonCmd = "py -3"; break }
        } else {
            $ver = & $candidate --version 2>&1
            if ($LASTEXITCODE -eq 0) { $pythonCmd = $candidate; break }
        }
    }
}
if (-not $pythonCmd) {
    Die "Python 3.10+ not found. Install from https://python.org/downloads/ (tick 'Add Python to PATH'), or `winget install Python.Python.3.13`, then re-run."
}
Ok "Using: $pythonCmd"

# Parse version
$verOutput = & $pythonCmd --version 2>&1
if ($verOutput -match "Python (\d+)\.(\d+)") {
    $major = [int]$Matches[1]; $minor = [int]$Matches[2]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        Die "Python 3.10+ required (you have $verOutput)."
    }
    Ok "Python $verOutput"
} else {
    Warn "Could not parse version from: $verOutput. Continuing anyway."
}

# ── Venv create / reuse ──────────────────────────────────────────────────────
$VenvDir = Join-Path $ScriptDir "venv"
$venvPython = Join-Path $VenvDir "Scripts\python.exe"
$venvPip = Join-Path $VenvDir "Scripts\pip.exe"

if (Test-Path $VenvDir) {
    if (Test-Path $venvPython) {
        Ok "Reusing existing venv at $VenvDir"
    } else {
        Die "Venv directory exists at $VenvDir but is missing Scripts\python.exe. Delete it and re-run."
    }
} else {
    Info "Creating venv at $VenvDir"
    & $pythonCmd -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Die "venv creation failed. Try running PowerShell as Administrator."
    }
    Ok "venv created"
}

# ── Install client requirements ─────────────────────────────────────────────
Info "Installing client requirements (this is small — no Whisper)..."
& $venvPython -m pip install --upgrade pip 2>&1 | Out-Null
& $venvPython -m pip install -r (Join-Path $ScriptDir "requirements-client.txt")
if ($LASTEXITCODE -ne 0) {
    Die "pip install failed. See the error above. Common causes: no internet, or the venv's pip is broken (delete $VenvDir and re-run)."
}
Ok "Client deps installed"

# ── .env ─────────────────────────────────────────────────────────────────────
$EnvFile = Join-Path $ScriptDir ".env"
$NeedEnv = $false

if (-not (Test-Path $EnvFile)) {
    $NeedEnv = $true
} else {
    # Check key vars are set to non-placeholder values
    $content = Get-Content $EnvFile -Raw
    foreach ($Var in @("HERMES_VOICE_WS_HOST", "HERMES_VOICE_WS_PORT", "GROQ_API_KEY")) {
        if ($content -notmatch "(?m)^${Var}=(.+)$") {
            $NeedEnv = $true; break
        }
        $val = ($content | Select-String "(?m)^${Var}=(.*)$").Matches[0].Groups[1].Value.Trim()
        if (-not $val -or $val -eq "your-groq-api-key-here" -or $val -eq "changeme") {
            $NeedEnv = $true; break
        }
    }
}

if ($NeedEnv) {
    Info "Need to (re)write .env with real values"

    # Default host/port from CLI args
    if ($GatewayHost) { $WS_HOST = $GatewayHost } else { $WS_HOST = "" }
    if ($GatewayPort) { $WS_PORT = $GatewayPort } else { $WS_PORT = "" }

    if (-not $WS_HOST) {
        Write-Host -NoNewline -ForegroundColor Yellow "Gateway host? (e.g. 192.168.1.3 or your-tailscale-host.tail*.ts.net): "
        $WS_HOST = Read-Host
        if (-not $WS_HOST) { Die "Gateway host is required." }
    }
    if (-not $WS_PORT) {
        $portPrompt = Read-Host "Gateway port? [7979]"
        $WS_PORT = if ($portPrompt) { $portPrompt } else { "7979" }
    }

    Write-Host -NoNewline -ForegroundColor Yellow "Groq API key? (or Enter to skip — set in .env later): "
    $secure = Read-Host -AsSecureString
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $GROQ_KEY = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) | Out-Null
    if (-not $GROQ_KEY) { $GROQ_KEY = "your-groq-api-key-here" }

    $envContent = @"
# hermes-voice client config
HERMES_VOICE_WS_HOST=$WS_HOST
HERMES_VOICE_WS_PORT=$WS_PORT
GROQ_API_KEY=$GROQ_KEY
"@
    Set-Content -Path $EnvFile -Value $envContent -NoNewline
    # Lock down file permissions — contains the API key
    $acl = Get-Acl $EnvFile
    $acl.SetAccessRuleProtection($true, $false)
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $env:USERNAME, "FullControl", "Allow")
    $acl.AddAccessRule($rule)
    Set-Acl $EnvFile $acl
    Ok ".env written (locked to $env:USERNAME only — contains secrets)"
} else {
    Ok ".env already configured"
}

# ── Smoke test ───────────────────────────────────────────────────────────────
Info "Smoke test: import the client module"
$importResult = & $venvPython -c "import hermes_voice.client; print('OK')" 2>&1
if ($importResult -notmatch "(?m)^OK$") {
    Die "Import failed. Output: $importResult"
}
Ok "Client imports cleanly"

# ── Done ─────────────────────────────────────────────────────────────────────
$wsHost = (Get-Content $EnvFile | Select-String "^HERMES_VOICE_WS_HOST=(.*)$").Matches[0].Groups[1].Value
$wsPort = (Get-Content $EnvFile | Select-String "^HERMES_VOICE_WS_PORT=(.*)$").Matches[0].Groups[1].Value

Write-Host ""
Write-Host "✓ bootstrap-client.ps1 complete" -ForegroundColor Green
Write-Host ""
Write-Host "To run the voice client:"
Write-Host "    .\venv\Scripts\python.exe -m hermes_voice.client"
Write-Host ""
Write-Host "Or use the launcher:"
Write-Host "    .\start-voice-client.ps1"
Write-Host ""
Write-Host "Targeting gateway at:"
Write-Host "    ws://${wsHost}:${wsPort}/ws"
Write-Host ""
Write-Host "If the gateway is on a different machine, make sure the port is"
Write-Host "reachable. Quick check:"
Write-Host "    Test-NetConnection -ComputerName $wsHost -Port $wsPort"
Write-Host ""
