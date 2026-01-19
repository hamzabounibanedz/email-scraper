# Script to help set up n8n secrets and authentication
# This will generate secure keys and help you configure .env

Write-Host "=== n8n Secret Key Setup ===" -ForegroundColor Green
Write-Host ""

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env file from env.example..." -ForegroundColor Yellow
    Copy-Item env.example .env
    Write-Host ".env file created!" -ForegroundColor Green
}
else {
    Write-Host ".env file already exists." -ForegroundColor Cyan
}

Write-Host ""
Write-Host "Generating secure encryption key..." -ForegroundColor Yellow

# Generate a secure 32-character encryption key
$encryptionKey = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ })

Write-Host ""
Write-Host "=== REQUIRED SECRETS ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. N8N_ENCRYPTION_KEY (Generated):" -ForegroundColor Yellow
Write-Host "   $encryptionKey" -ForegroundColor White
Write-Host ""
Write-Host "2. N8N_BASIC_AUTH_PASSWORD (You need to set this):" -ForegroundColor Yellow
Write-Host "   Choose a strong password for n8n UI access" -ForegroundColor White
Write-Host ""

# Prompt for password
$password = Read-Host "Enter a password for n8n admin access (or press Enter to skip)"
if ($password) {
    Write-Host ""
    Write-Host "Updating .env file..." -ForegroundColor Yellow
    
    # Read current .env
    $envContent = Get-Content .env -Raw
    
    # Replace encryption key
    $envContent = $envContent -replace 'N8N_ENCRYPTION_KEY=.*', "N8N_ENCRYPTION_KEY=$encryptionKey"
    
    # Replace password
    $envContent = $envContent -replace 'N8N_BASIC_AUTH_PASSWORD=.*', "N8N_BASIC_AUTH_PASSWORD=$password"
    
    # Write back
    Set-Content .env -Value $envContent -NoNewline
    
    Write-Host ""
    Write-Host ".env file updated with encryption key and password!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Your n8n credentials:" -ForegroundColor Cyan
    Write-Host "  Username: admin" -ForegroundColor White
    Write-Host "  Password: $password" -ForegroundColor White
}
else {
    Write-Host ""
    Write-Host "Please manually edit .env and set:" -ForegroundColor Yellow
    Write-Host "  N8N_ENCRYPTION_KEY=$encryptionKey" -ForegroundColor White
    Write-Host "  N8N_BASIC_AUTH_PASSWORD=your_strong_password" -ForegroundColor White
}

Write-Host ""
Write-Host "=== NEXT STEPS ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Review .env file to ensure all settings are correct" -ForegroundColor White
Write-Host "2. Start n8n with: .\start.ps1" -ForegroundColor White
Write-Host "   OR: docker-compose up -d" -ForegroundColor White
Write-Host "3. Access n8n at: http://localhost:5678" -ForegroundColor White
Write-Host ""
Write-Host "=== IMPORTANT ===" -ForegroundColor Red
Write-Host "Keep your .env file secure and never commit it to git!" -ForegroundColor Yellow
Write-Host ""
