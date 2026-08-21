# ==============================================================================
# TARANG CLINICAL HUB — WINDOWS POWERSHELL LAUNCHER
# ==============================================================================

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $Root "dashboard\backend"
$FrontendDir = Join-Path $Root "dashboard\frontend"

Write-Host "[1/3] Starting FastAPI Backend on port 8000..." -ForegroundColor Cyan
$BackendJob = Start-Process -FilePath "uvicorn" -ArgumentList "main:app --host 0.0.0.0 --port 8000" -WorkingDirectory $BackendDir -PassThru

Start-Sleep -Seconds 2

Write-Host "[2/3] Starting Next.js Frontend on port 3000..." -ForegroundColor Cyan
$FrontendJob = Start-Process -FilePath "npm" -ArgumentList "run dev" -WorkingDirectory $FrontendDir -PassThru

Start-Sleep -Seconds 3

Write-Host "[3/3] Opening Clinical Dashboard in Browser..." -ForegroundColor Green
Start-Process "http://localhost:3000"

Write-Host "`n==========================================" -ForegroundColor Yellow
Write-Host "  TARANG CLINICAL HUB RUNNING" -ForegroundColor Yellow
Write-Host "  Dashboard : http://localhost:3000" -ForegroundColor Yellow
Write-Host "  API       : http://localhost:8000" -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Yellow
Write-Host "Press Ctrl+C or close this window to exit."

try {
    while ($true) {
        Start-Sleep -Seconds 1
    }
} finally {
    Write-Host "`nStopping services..." -ForegroundColor Red
    Stop-Process -Id $BackendJob.Id -ErrorAction SilentlyContinue
    Stop-Process -Id $FrontendJob.Id -ErrorAction SilentlyContinue
}
