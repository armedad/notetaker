# Notetaker Start Script
param(
    [switch]$Debug,
    [switch]$Help
)

$Host.UI.RawUI.WindowTitle = "Notetaker"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

function Get-VenvPython {
    $candidates = @()
    if ($env:CHEEAPPS_VENV -and $env:CHEEAPPS_VENV.Trim()) { $candidates += $env:CHEEAPPS_VENV.Trim() }
    $marker = Join-Path $ProjectDir ".notetaker_venv"
    if (Test-Path -LiteralPath $marker) {
        $line = (Get-Content -LiteralPath $marker -TotalCount 1 -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($line -and "$line".Trim()) { $candidates += "$line".Trim() }
    }
    $candidates += (Join-Path (Split-Path -Parent $ProjectDir) ".env")
    $candidates += (Join-Path $ProjectDir ".venv")
    foreach ($raw in $candidates) {
        try { $dir = [System.IO.Path]::GetFullPath($raw) } catch { continue }
        $py = Join-Path $dir "Scripts\python.exe"
        if ((Test-Path -LiteralPath (Join-Path $dir "pyvenv.cfg")) -and (Test-Path -LiteralPath $py)) { return $py }
    }
    throw "No valid venv. Run install.bat or set CHEEAPPS_VENV (e.g. X:\.env)."
}

$venvPython = Get-VenvPython
$serveArgs = @()
if ($Debug) { $serveArgs += "-debug" }
if ($Help) { $serveArgs += "-help" }

if (-not $Help) {
    $env:NOTETAKER_LOCAL_SHUTDOWN = "1"
    $debugLiteral = if ($Debug) { "True" } else { "False" }
    $port = [int](& $venvPython -c "from app.paths import ensure_install_cwd; ensure_install_cwd(); from app.cli import resolve_port; print(resolve_port(debug=$debugLiteral))")
    Write-Host "Starting Notetaker server..."
    Write-Host "Python: $venvPython"
    Write-Host "Web interface: http://127.0.0.1:$port"
    if ($Debug) {
        Write-Host "Mode: debug (verbose logging, all debug flags on)"
    }
    Write-Host "Press Ctrl+C to stop"
    Write-Host ""
}

& $venvPython "$ProjectDir\serve.py" @serveArgs
