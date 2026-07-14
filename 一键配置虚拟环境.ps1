$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$appDir = Join-Path $root "app"
$venvDir = Join-Path $root ".venv"

python -m venv $venvDir

$pythonExe = Join-Path $venvDir "Scripts\\python.exe"

& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install -r (Join-Path $appDir "requirements.txt")
& $pythonExe -m pip install $appDir

Write-Host "虚拟环境已完成，可使用以下命令启动：" -ForegroundColor Green
Write-Host "$pythonExe -m uvicorn article_check.web.server:app --host 127.0.0.1 --port 8765"
