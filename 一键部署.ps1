$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = Join-Path $root "app"
$envFile = Join-Path $appDir ".env.platform"
$exampleFile = Join-Path $appDir ".env.platform.example"

if (-not (Test-Path $appDir)) {
    throw "app directory not found: $appDir"
}

if (-not (Test-Path $envFile)) {
    Copy-Item $exampleFile $envFile
    Write-Host "Created .env.platform. Fill real env vars and run again." -ForegroundColor Yellow
    exit 0
}

Push-Location $appDir
try {
    & docker compose -f docker-compose.platform.yml --env-file .env.platform up -d --build
} finally {
    Pop-Location
}
