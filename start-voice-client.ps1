# start-voice-client.ps1 — launch the hermes-voice Python voice client on Windows.
#
# Run from a repo that has been bootstrapped (run bootstrap-client.ps1 once first).
# Equivalent to: .\venv\Scripts\python.exe -m hermes_voice.client
#
# Usage:
#   .\start-voice-client.ps1                  # normal run
#   .\start-voice-client.ps1 -ListDevices     # print available input/output devices
#   .\start-voice-client.ps1 -InputDevice 5   # force a specific input device
#   .\start-voice-client.ps1 -Headless        # no console log spam (uses WARN level)
#
# Press Ctrl+C to stop.

[CmdletBinding()]
param(
    [string]$InputDevice = "",
    [string]$OutputDevice = "",
    [switch]$ListDevices,
    [switch]$Headless
)

$ErrorActionPreference = "Stop"

# ── Find repo root (this script lives in the repo) ───────────────────────────
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
}
Set-Location $ScriptDir

# ── Locate venv python ───────────────────────────────────────────────────────
$VenvPython = Join-Path $ScriptDir "venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "ERROR: venv not found at $VenvPython" -ForegroundColor Red
    Write-Host "Run bootstrap-client.ps1 first to install the client." -ForegroundColor Yellow
    exit 1
}

# ── Verify .env exists ──────────────────────────────────────────────────────
$EnvFile = Join-Path $ScriptDir ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Host "ERROR: .env not found at $EnvFile" -ForegroundColor Red
    Write-Host "Run bootstrap-client.ps1 to create it." -ForegroundColor Yellow
    exit 1
}

# ── Optional: list devices and exit ─────────────────────────────────────────
if ($ListDevices) {
    Write-Host "Audio devices:" -ForegroundColor Cyan
    & $VenvPython -c "import sounddevice; print(sounddevice.query_devices())"
    exit 0
}

# ── Build environment for the child process ─────────────────────────────────
$env:HOME = $env:USERPROFILE                 # some Python packages look at HOME
$env:PYTHONUNBUFFERED = "1"                  # see log output immediately

# Forward any -InputDevice / -OutputDevice overrides
if ($InputDevice)    { $env:HERMES_VOICE_INPUT_DEVICE  = $InputDevice }
if ($OutputDevice)   { $env:HERMES_VOICE_OUTPUT_DEVICE = $OutputDevice }

# Headless mode: quieter logs (only warnings and above)
if ($Headless) {
    $env:HERMES_VOICE_LOG_LEVEL = "WARNING"
}

# ── Launch ───────────────────────────────────────────────────────────────────
$wsHost = (Get-Content $EnvFile | Select-String "^HERMES_VOICE_WS_HOST=(.*)$").Matches[0].Groups[1].Value
$wsPort = (Get-Content $EnvFile | Select-String "^HERMES_VOICE_WS_PORT=(.*)$").Matches[0].Groups[1].Value

Write-Host "Starting hermes-voice client" -ForegroundColor Cyan
Write-Host "  Target: ws://${wsHost}:${wsPort}/ws"
if ($InputDevice)  { Write-Host "  Input device index: $InputDevice" }
if ($OutputDevice) { Write-Host "  Output device index: $OutputDevice" }
Write-Host "  Press Ctrl+C to stop." -ForegroundColor Yellow
Write-Host ""

& $VenvPython -m hermes_voice.client
