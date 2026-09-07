# Windows 一键安装（PowerShell 5.1+；升级用 upgrade-windows.ps1）
# 用法：在项目根目录执行
#   1) copy deploy\windows\deploy.conf.example deploy\windows\deploy.conf 并填写
#   2) powershell -ExecutionPolicy Bypass -File deploy\windows\install-windows.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# ---- 读取配置（占位符校验） ----
$confPath = Join-Path $root "deploy\windows\deploy.conf"
if (-not (Test-Path $confPath)) {
    Copy-Item (Join-Path $root "deploy\windows\deploy.conf.example") $confPath
    Write-Host "已生成 $confPath，请填写 __XXX__ 占位符后重新执行"
    exit 1
}
$conf = @{}
Get-Content $confPath | ForEach-Object {
    if ($_ -match '^\s*([A-Z_]+)\s*=\s*(.*)$') { $conf[$matches[1]] = $matches[2].Trim() }
}
foreach ($k in @("APP_HOME", "PORT")) {
    $v = $conf[$k]
    if (-not $v -or $v -like "*__*") { throw "配置项 $k 未填写或仍是占位符：deploy\windows\deploy.conf" }
}
$APP_HOME = $conf["APP_HOME"]; $PORT = $conf["PORT"]
$TASK_NAME = if ($conf["TASK_NAME"]) { $conf["TASK_NAME"] } else { "SuperTools" }
$RETENTION = if ($conf["RETENTION_DAYS"]) { $conf["RETENTION_DAYS"] } else { "90" }
Write-Host "部署到 $APP_HOME 端口 $PORT 任务 $TASK_NAME"

$serverDir = Join-Path $APP_HOME "server"
$webDir = Join-Path $APP_HOME "web"
New-Item -ItemType Directory -Force -Path (Join-Path $APP_HOME "logs") | Out-Null

Write-Host "== 1/6 检查环境 =="
$pyCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pyCmd) { $pyCmd = Get-Command py -ErrorAction SilentlyContinue }
if (-not $pyCmd) { throw "未找到 Python（需 3.10+），安装时勾选 Add to PATH：https://www.python.org/downloads/" }
$python = $pyCmd.Source
& $python --version
$node = Get-Command node -ErrorAction SilentlyContinue

Write-Host "== 2/6 复制代码到部署目录 =="
if ((Resolve-Path $root).Path -ne (Resolve-Path $APP_HOME).Path) {
    New-Item -ItemType Directory -Force -Path $APP_HOME | Out-Null
    foreach ($d in @("server", "web", "docs", "deploy", "skills")) {
        if (Test-Path (Join-Path $root $d)) {
            robocopy (Join-Path $root $d) (Join-Path $APP_HOME $d) /E /NFL /NDL /NJH /NJS /NP | Out-Null
            if ($LASTEXITCODE -ge 8) { throw "复制 $d 失败" }
        }
    }
    Copy-Item (Join-Path $root "VERSION") (Join-Path $APP_HOME "VERSION") -Force -ErrorAction SilentlyContinue
}

Write-Host "== 3/6 后端虚拟环境与测试 =="
Push-Location $serverDir
if (-not (Test-Path "venv")) { & $python -m venv venv }
$vpip = Join-Path $serverDir "venv\Scripts\python.exe"
& $vpip -m pip install -q -r requirements.txt -r requirements-dev.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
& $vpip -m pytest -q
Pop-Location

Write-Host "== 4/6 生成独立配置（server\.env）=="
$envFile = Join-Path $serverDir ".env"
New-Item -ItemType Directory -Force -Path (Join-Path $serverDir "data") | Out-Null
$jwt = $conf["JWT_SECRET"]
if (-not $jwt) { $jwt = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N") }
@"
DATABASE_URL=sqlite:///./data/app.db
JWT_SECRET=$jwt
STATIC_DIR=..\web\dist
LOG_RETENTION_DAYS=$RETENTION
"@ | Out-File -Encoding ascii $envFile
Write-Host "已生成 $envFile（如需 PostgreSQL，修改 DATABASE_URL 并补装 psycopg2-binary）"

Write-Host "== 5/6 构建前端 =="
if ($node) {
    Push-Location $webDir
    & npm install --registry=https://registry.npmmirror.com --no-fund --no-audit
    & npm run test
    & npm run build
    Pop-Location
} elseif (Test-Path (Join-Path $webDir "dist\index.html")) {
    Write-Host "未安装 Node，复用已有 dist（发布包内含预构建 dist 时适用）"
} else {
    Write-Warning "未安装 Node 且无已构建 dist，前端不可用。安装 Node 后重跑：https://nodejs.org/"
}

Write-Host "== 6/6 注册开机自启服务（计划任务 $TASK_NAME，端口 $PORT）=="
$runCmd = Join-Path $APP_HOME "deploy\windows\run-backend.cmd"
# 生成实际运行脚本（写入端口）
@"
@echo off
rem 由 install-windows.ps1 生成：uvicorn 退出后 5 秒自动重启
set PORT=$PORT
cd /d "$serverDir"
:loop
"venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT% >> "..\logs\backend.log" 2>&1
timeout /t 5 /nobreak >nul
goto loop
"@ | Out-File -Encoding ascii $runCmd
schtasks /Create /TN "$TASK_NAME" /TR "`"$runCmd`"" /SC ONSTART /RU SYSTEM /RL HIGHEST /F | Out-Null
schtasks /Run /TN "$TASK_NAME" | Out-Null
Start-Sleep -Seconds 6
$probe = $null
try { $probe = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$PORT/" -TimeoutSec 10 } catch {}
if ($probe -and $probe.StatusCode -eq 200) {
    Write-Host "部署完成！访问 http://本机IP:$PORT/ （初始账号 admin/admin123）"
} else {
    Write-Warning "服务未在 6 秒内就绪，查看 $APP_HOME\logs\backend.log 或稍后 schtasks /Run /TN $TASK_NAME"
}
Write-Host "卸载服务: schtasks /Delete /TN $TASK_NAME /F"
