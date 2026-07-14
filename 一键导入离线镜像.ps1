$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$imageDir = Join-Path $root "镜像包"

if (-not (Test-Path $imageDir)) {
    throw "image bundle directory not found: $imageDir"
}

$archives = Get-ChildItem $imageDir -Filter *.tar | Sort-Object Name

if (-not $archives) {
    throw "no image archive found in: $imageDir"
}

foreach ($archive in $archives) {
    Write-Host ("Importing image archive: " + $archive.Name) -ForegroundColor Cyan
    & docker load -i $archive.FullName
}

Write-Host "Offline image import completed." -ForegroundColor Green
