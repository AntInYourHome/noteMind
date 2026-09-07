# Windows 日常发布：代码更新后执行（读 deploy\windows\deploy.conf）
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$confPath = Join-Path $root "deploy\windows\deploy.conf"
if (-not (Test-Path $confPath)) { throw "缺少 $confPath，请先执行 install-windows.ps1" }
$conf = @{}
Get-Content $confPath | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)$') { $conf[$matches[1]] = $matches[2].Trim() }
}
$APP_HOME = $conf["APP_HOME"]; $PORT = $conf["PORT"]
$TASK_NAME = if ($conf["TASK_NAME"]) { $conf["TASK_NAME"] } else { "SuperTools" }
$serverDir = Join-Path $APP_HOME "server"; $webDir = Join-Path $APP_HOME "web"

Write-Host "== 同步代码 =="
foreach ($d in @("server", "web", "deploy", "docs", "skills")) {
    if (Test-Path (Join-Path $root $d)) {
        robocopy (Join-Path $root $d) (Join-Path $APP_HOME $d) /E /NFL /NDL /NJH /NJS /NP /XD venv node_modules dist data | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "同步 $d 失败" }
    }
}

Write-Host "== 后端测试 =="
$vpip = Join-Path $serverDir "venv\Scripts\python.exe"
& $vpip -m pip install -q -r (Join-Path $serverDir "requirements.txt") -r (Join-Path $serverDir "requirements-dev.txt") -i https://pypi.tuna.tsinghua.edu.cn/simple
Push-Location $serverDir; & $vpip -m pytest -q; Pop-Location

Write-Host "== 构建前端 =="
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    Push-Location $webDir
    & npm install --registry=https://registry.npmmirror.com --no-fund --no-audit
    & npm run test
    & npm run build
    Pop-Location
} else { Write-Warning "未安装 Node，跳过前端构建" }

Write-Host "== 重启服务 =="
schtasks /End /TN "$TASK_NAME" 2>$null | Out-Null
schtasks /Run /TN "$TASK_NAME" | Out-Null
Start-Sleep -Seconds 6
$probe = $null
try { $probe = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$PORT/" -TimeoutSec 10 } catch {}
if ($probe) { Write-Host "发布完成（服务运行中）" }
else { Write-Warning "服务未就绪，查看 $APP_HOME\logs\backend.log" }
