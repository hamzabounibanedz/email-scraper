# Stop script for n8n Email Agent

Write-Host "Stopping n8n Email Agent..." -ForegroundColor Yellow

docker-compose down

if ($LASTEXITCODE -eq 0) {
    Write-Host "n8n stopped successfully." -ForegroundColor Green
} else {
    Write-Host "Error stopping n8n." -ForegroundColor Red
    exit 1
}
