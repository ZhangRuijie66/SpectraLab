# ============================================================
#  v4.28 收尾脚本（一次跑完：splash → mac 同步 → 打包 → 校验 → 提交）
# ------------------------------------------------------------
#  背景：2026-09-10 晚，D:\北大\光谱工具\可视化分析GUI 目录对进程
#  "时隐时现"（PowerShell 只看到 4 个条目、Python 只看到 1 个 .py，
#  子进程 spawn ENOENT，Edge 也崩过），导致发版步骤无法可靠完成。
#  本脚本放在 C 盘，**等文件系统健康了再一键跑**，避免手工重复。
#
#  用法（PowerShell）：
#     powershell -ExecutionPolicy Bypass -File "C:\Users\zhang\AppData\Local\Temp\spectra_v428_backup\finish_v428.ps1"
#  可选参数：-WaitMinutes 10      等健康窗口的最长分钟数
#            -SkipPackage        只做校验/提交，不打包
#
#  每步都先等"健康窗口"（目录条目 > 20 且 gui_config.py 可读），
#  并写日志到 GUI\tests\_diag\finish_v428.log
# ============================================================
param(
    [int]$WaitMinutes = 10,
    [switch]$SkipPackage
)

$ErrorActionPreference = "Continue"
$G = "D:\北大\光谱工具\可视化分析GUI"
$R = Split-Path $G -Parent
$LOG = Join-Path $G "tests\_diag\finish_v428.log"

function Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Host $line
    try { Add-Content -LiteralPath $LOG -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue } catch {}
}

function Test-Healthy {
    try {
        $n = @(Get-ChildItem -LiteralPath $G -Force -ErrorAction SilentlyContinue).Count
        if ($n -le 20) { return $false }
        return (Test-Path -LiteralPath (Join-Path $G "gui_config.py"))
    } catch { return $false }
}

function Wait-Healthy([string]$what) {
    $deadline = (Get-Date).AddMinutes($WaitMinutes)
    $i = 0
    while ((Get-Date) -lt $deadline) {
        $i++
        if (Test-Healthy) { Log "健康窗口就绪（第 $i 次检查），继续：$what"; return $true }
        if ($i % 10 -eq 0) { Log "仍异常（第 $i 次检查），等待中…" }
        Start-Sleep -Seconds 3
    }
    Log "!! 等了 $WaitMinutes 分钟仍未见健康窗口，停在这里：$what"
    return $false
}

function Run-Py([string]$relPath, [string]$logName) {
    Push-Location -LiteralPath $G
    try {
        python $relPath *> (Join-Path $G "tests\_diag\$logName")
        return $LASTEXITCODE
    } finally { Pop-Location }
}

Log "================ v4.28 收尾开始 ================"

# ---------- 0) 健康检查 ----------
if (-not (Wait-Healthy "开始收尾")) { exit 3 }

# ---------- 1) 升版号确认 ----------
$cfg = Join-Path $G "gui_config.py"
$ver = (Select-String -LiteralPath $cfg -Pattern 'APP_VERSION = "([\d.]+)"').Matches[0].Groups[1].Value
Log "当前 APP_VERSION = $ver"
if ($ver -ne "4.28") {
    Log "版本号不是 4.28，尝试改…"
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $t = [System.IO.File]::ReadAllText($cfg, $utf8)
    $t2 = [regex]::Replace($t, 'APP_VERSION = "\d+\.\d+"', 'APP_VERSION = "4.28"')
    [System.IO.File]::WriteAllText($cfg, $t2, $utf8)
    Log "已改为 4.28（请复核）"
}

# ---------- 2) 重生成 splash（深色 + 版本号写进 PNG 元数据）----------
if (-not (Wait-Healthy "重生成 splash")) { exit 3 }
$code = Run-Py "tests\_diag\ascii_runner.py splash" "finish_splash.log"
Log "splash 退出码 = $code"
Get-Content -LiteralPath (Join-Path $G "tests\_diag\finish_splash.log") -Encoding UTF8 -ErrorAction SilentlyContinue |
    Select-Object -Last 2 | ForEach-Object { Log "  $_" }

# ---------- 3) 同步到 mac 文件夹 ----------
if (-not (Wait-Healthy "同步 mac 文件夹")) { exit 3 }
Push-Location -LiteralPath $G
powershell -ExecutionPolicy Bypass -File "同步到mac文件夹.ps1" *> (Join-Path $G "tests\_diag\finish_sync.log")
Log "mac 同步退出码 = $LASTEXITCODE（2 = 仅 exe 新鲜度未过，属预期）"
Pop-Location
Get-Content -LiteralPath (Join-Path $G "tests\_diag\finish_sync.log") -Encoding Default -ErrorAction SilentlyContinue |
    Select-String -Pattern "清单条目|展开文件|缺失跳过|哈希" | ForEach-Object { Log "  $($_.Line.Trim())" }

# ---------- 4) 打包便携版 ----------
if (-not $SkipPackage) {
    if (-not (Wait-Healthy "打包便携版")) { exit 3 }
    Push-Location -LiteralPath $G
    powershell -ExecutionPolicy Bypass -File "打包便携版.ps1" *> (Join-Path $G "tests\_diag\finish_pack.log")
    Log "打包退出码 = $LASTEXITCODE"
    Pop-Location
    Get-Content -LiteralPath (Join-Path $G "tests\_diag\finish_pack.log") -Encoding Default -ErrorAction SilentlyContinue |
        Select-Object -Last 6 | ForEach-Object { Log "  $_" }

    # ---------- 5) 启动测试 ----------
    $exe = Join-Path $G "便携版\光谱可视化分析工具.exe"
    if (Test-Path -LiteralPath $exe) {
        $fi = Get-Item -LiteralPath $exe
        Log "exe: $($fi.Length) 字节, $($fi.LastWriteTime)"
        $p = Start-Process -FilePath $exe -PassThru
        Start-Sleep -Seconds 45
        $kids = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.Id)" -ErrorAction SilentlyContinue |
                  Select-Object -ExpandProperty ProcessId)
        Log "启动测试: 父进程存活=$(-not $p.HasExited) 子进程=[$($kids -join ',')]"
        foreach ($k in $kids) { Stop-Process -Id $k -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Log "清理后残留: " + @(Get-Process | Where-Object { $_.ProcessName -like '*光谱*' }).Count
    } else { Log "!! 没找到便携版 exe" }
}

# ---------- 6) 版本一致性 + 回归 ----------
if (-not (Wait-Healthy "版本一致性 + 回归")) { exit 3 }
$code = Run-Py "tests\_diag\ascii_runner.py vercheck" "finish_vercheck.log"
Log "版本一致性退出码 = $code"
Get-Content -LiteralPath (Join-Path $G "tests\_diag\finish_vercheck.log") -Encoding UTF8 -ErrorAction SilentlyContinue |
    Select-String -Pattern "总|FAIL" | Select-Object -Last 4 | ForEach-Object { Log "  $($_.Line.Trim())" }

$env:QT_QPA_PLATFORM = "offscreen"
$env:QT_QPA_FONTDIR = "$env:WINDIR\Fonts"
$code = Run-Py "tests\run_regression.py" "finish_regression.log"
Log "回归退出码 = $code"
Get-Content -LiteralPath (Join-Path $G "tests\_diag\finish_regression.log") -Encoding UTF8 -ErrorAction SilentlyContinue |
    Select-String -Pattern "共 \d+ 项|FAIL" | ForEach-Object { Log "  $($_.Line.Trim())" }

# ---------- 7) git 提交 ----------
if (-not (Wait-Healthy "git 提交")) { exit 3 }
Push-Location -LiteralPath $G
$msgFile = Join-Path $env:TEMP "spectra_v428_backup\commit_v428.txt"
git add gui_config.py gui_ui.py gui_data.py gui_help.py gui_launcher.py gui_splash.py gui_icons.py gui_components.py `
        生成图标.py 生成splash图.py icons splash.png tests/run_regression.py tests/test_icons_smoke.py `
        tests/test_help_dialog_smoke.py "UI设计方案_讨论稿.md" "更新日志/CHANGELOG_v428.md" 2>&1 |
    ForEach-Object { Log "  $_" }
$staged = (git diff --cached --name-only | Measure-Object -Line).Lines
Log "已暂存 $staged 个文件"
if ($staged -gt 0) {
    git commit -q -F $msgFile
    Log "提交退出码 = $LASTEXITCODE"
    git log --oneline -2 | ForEach-Object { Log "  $_" }
    git status --short | Select-Object -First 5 | ForEach-Object { Log "  未提交: $_" }
} else { Log "没有需要提交的改动" }
Pop-Location

Log "================ v4.28 收尾结束 ================"
