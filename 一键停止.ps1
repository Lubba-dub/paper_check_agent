$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = Join-Path $root "app"
$envFile = Join-Path $appDir ".env.platform"

Push-Location $appDir
try {
    if (Test-Path $envFile) {
        & docker compose -f docker-compose.platform.yml --env-file .env.platform down --remove-orphans
    } else {
        & docker compose -f docker-compose.platform.yml down --remove-orphans
    }
} finally {
    Pop-Location
}
