# Quick start script for n8n Email Agent
# Run this script to start n8n with Docker Compose

Write-Host "Starting n8n Email Agent..." -ForegroundColor Green

# Check if .env file exists
if (-not (Test-Path ".env")) {
    Write-Host "Warning: .env file not found!" -ForegroundColor Yellow
    Write-Host "Please copy env.example to .env and configure it first." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "You can do this with:" -ForegroundColor Cyan
    Write-Host "  Copy-Item env.example .env" -ForegroundColor Cyan
    Write-Host ""
    $continue = Read-Host "Continue anyway? (y/N)"
    if ($continue -ne "y" -and $continue -ne "Y") {
        exit
    }
}

# Check if Docker is running
try {
    docker info | Out-Null
}
catch {
    Write-Host "Error: Docker is not running!" -ForegroundColor Red
    Write-Host "Please start Docker Desktop and try again." -ForegroundColor Red
    exit 1
}

# Start Docker Compose
Write-Host "Starting Docker Compose..." -ForegroundColor Cyan
docker-compose up -d

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "n8n is starting up..." -ForegroundColor Green
    Write-Host "Wait 30-60 seconds, then open:" -ForegroundColor Cyan
    Write-Host "  http://localhost:5678" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "To view logs:" -ForegroundColor Cyan
    Write-Host "  docker-compose logs -f n8n" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "To stop n8n:" -ForegroundColor Cyan
    Write-Host "  docker-compose down" -ForegroundColor Yellow
}
else {
    Write-Host "Error starting n8n. Check the output above for details." -ForegroundColor Red
    exit 1
}
