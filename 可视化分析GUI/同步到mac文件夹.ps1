# ============================================================
#  同步 GUI 源码到 mac 打包文件夹（E2 / F6）
# ------------------------------------------------------------
#  作用：把 Windows 侧的 GUI 源码 + 画图模块 + 资源目录复制到 mac打包文件夹\，
#        避免历史上"漏装某个模块导致 mac 打包失败/运行报 ImportError"。
#  用法：在 可视化分析GUI 目录下执行
#        powershell -ExecutionPolicy Bypass -File 同步到mac文件夹.ps1
#  行为：
#    * 待同步清单见下方 SYNC-MANIFEST 区块——**清单唯一真源**，
#      检查版本一致性.py 会解析同一区块做逐文件 SHA256 比对，别在别处再抄一份。
#    * 只复制**存在**的条目；缺失的打印警告并继续（标了 optional 的只提示，不算失败）
#    * 复制后逐个文件比对 **SHA256**（源 vs 目标）；旧版只比字节数，
#      改一行同长度的代码就检测不出来，已废弃。
#    * 同步结束后自动跑一次 检查版本一致性.py（只读检查，不会改文件）
#  注意：本脚本会**覆盖** mac打包文件夹 中的同名文件。
#  编码：本文件必须是 UTF-8 **带 BOM**（EF BB BF），否则 PowerShell 5.1 会把中文读成乱码。
# ============================================================

$ErrorActionPreference = "Stop"

$appdir  = $PSScriptRoot                       # 本脚本所在目录（GUI 根目录）
$parent  = Split-Path $appdir -Parent          # 上级目录（含 plot_*.py 等）
$dest    = Join-Path $appdir "mac打包文件夹"     # 目标目录
$checker = Join-Path $appdir "检查版本一致性.py"  # 同步后自动运行的只读检查

Write-Host "=========================================================="
Write-Host "  同步 GUI 源码 -> mac 打包文件夹（SHA256 校验）"
Write-Host "  源目录    : $appdir"
Write-Host "  模块目录  : $parent"
Write-Host "  目标目录  : $dest"
Write-Host "=========================================================="
Write-Host ""

if (-not (Test-Path -LiteralPath $dest)) {
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Write-Host "[新建] 目标目录不存在，已创建。"
    Write-Host ""
}

# >>> SYNC-MANIFEST BEGIN
# ------------------------------------------------------------
#  待同步清单（**唯一真源**；检查版本一致性.py 解析本区块）
# ------------------------------------------------------------
#  条目格式："scope|相对路径[|optional]"
#    scope = app        源在 $appdir（可视化分析GUI 目录）
#            parent     源在 $parent（上级 画图 目录）
#            appdir     源是 $appdir 下的**目录**，递归同步（目标保留子目录结构）
#            parentdir  源是 $parent 下的**目录**，递归同步
#    第三段写 optional：源缺失时只提示、不计入"缺失"（如 app_icon.png 目前只在 mac 副本里）
$manifest = @(
    # ---- GUI 根目录下的源码与资源 ----
    "app|absorption_gui.py",
    "app|entry_gui.py",
    "app|start_gui.py",
    "app|launch_hidden.py",
    "app|gui_ui.py",
    "app|gui_data.py",
    "app|gui_plot.py",
    "app|gui_config.py",
    "app|gui_components.py",
    "app|gui_launcher.py",
    "app|gui_splash.py",
    "app|app_icon.ico",
    "app|app_icon.png|optional",
    "app|splash.png",
    "app|生成splash图.py",
    "app|requirements.txt",
    # ---- GUI 根目录下的目录（递归）----
    "appdir|icons",
    "appdir|更新日志",
    # ---- 上级 画图 目录下的绘图模块 ----
    "parent|plot_absorption.py",
    "parent|plot_emission.py",
    "parent|plot_lifetime.py",
    "parent|plot_3d_scan.py",
    "parent|read_xlsx_info.py",
    "parent|curve_colors.py"
)
# <<< SYNC-MANIFEST END

# ---- 展开清单为 (源文件, 目标相对路径) 计划表 ----
$plan     = New-Object System.Collections.ArrayList
$missing  = New-Object System.Collections.ArrayList
$mismatch = New-Object System.Collections.ArrayList
$rows     = New-Object System.Collections.ArrayList

foreach ($entry in $manifest) {
    $parts = @($entry -split "\|")
    if ($parts.Count -lt 2) {
        Write-Host ("[警告] 清单条目格式不对，已跳过：{0}" -f $entry)
        continue
    }
    $scope    = $parts[0].Trim()
    $rel      = $parts[1].Trim()
    $optional = ($parts.Count -ge 3) -and ($parts[2].Trim().ToLower() -eq "optional")

    switch ($scope) {
        "app"       { $srcRoot = $appdir; $isDir = $false }
        "parent"    { $srcRoot = $parent; $isDir = $false }
        "appdir"    { $srcRoot = $appdir; $isDir = $true }
        "parentdir" { $srcRoot = $parent; $isDir = $true }
        default {
            Write-Host ("[警告] 清单条目 scope 不认识，已跳过：{0}" -f $entry)
            continue
        }
    }

    $srcPath = Join-Path $srcRoot $rel

    if ($isDir) {
        if (-not (Test-Path -LiteralPath $srcPath -PathType Container)) {
            if ($optional) {
                Write-Host ("[信息] 可选目录不存在，已跳过：{0}" -f $rel)
            } else {
                Write-Host ("[警告] 源目录不存在，已跳过：{0}" -f $rel)
                [void]$missing.Add($rel)
            }
            continue
        }
        foreach ($f in (Get-ChildItem -LiteralPath $srcPath -Recurse -File -Force)) {
            $sub = $f.FullName.Substring($srcPath.Length).TrimStart("\", "/")
            $relDest = Join-Path $rel $sub
            [void]$plan.Add([PSCustomObject]@{ Src = $f.FullName; Rel = $relDest; Optional = $optional })
        }
    }
    else {
        if (-not (Test-Path -LiteralPath $srcPath -PathType Leaf)) {
            if ($optional) {
                Write-Host ("[信息] 可选文件不存在，已跳过：{0}" -f $rel)
            } else {
                Write-Host ("[警告] 源文件不存在，已跳过：{0}" -f $rel)
                [void]$missing.Add($rel)
            }
            continue
        }
        [void]$plan.Add([PSCustomObject]@{ Src = $srcPath; Rel = $rel; Optional = $optional })
    }
}

Write-Host ""
Write-Host "---- 开始复制（逐个文件 SHA256 校验） ----"
$copied = 0
foreach ($item in $plan) {
    $dst = Join-Path $dest $item.Rel
    $dstDir = Split-Path $dst -Parent
    if (-not (Test-Path -LiteralPath $dstDir)) {
        New-Item -ItemType Directory -Force -Path $dstDir | Out-Null
    }

    Copy-Item -LiteralPath $item.Src -Destination $dst -Force

    $hashSrc = (Get-FileHash -LiteralPath $item.Src -Algorithm SHA256).Hash
    $hashDst = (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash
    $ok = ($hashSrc -eq $hashDst)
    if (-not $ok) { [void]$mismatch.Add($item.Rel) }

    $copied++
    [void]$rows.Add([PSCustomObject]@{
        Name   = $item.Rel
        Sha256 = $hashDst.Substring(0, 12)
        Check  = $(if ($ok) { "OK" } else { "HASH-MISMATCH" })
    })
}
Write-Host ""

# ---- 逐文件结果 ----
Write-Host "---- 复制结果（SHA256 前 12 位） ----"
foreach ($r in $rows) {
    Write-Host ("  {0,-32} {1}  {2}" -f $r.Name, $r.Sha256, $r.Check)
}
Write-Host ""

# ---- 总结 ----
Write-Host "=========================================================="
Write-Host "  同步总结"
Write-Host ("    清单条目 : {0} 条" -f $manifest.Count)
Write-Host ("    展开文件 : {0} 个" -f $plan.Count)
Write-Host ("    实际复制 : {0} 个文件" -f $copied)
Write-Host ("    缺失跳过 : {0} 个" -f $missing.Count)
Write-Host ("    哈希不一致: {0} 个" -f $mismatch.Count)

if ($missing.Count -gt 0) {
    Write-Host ("    [警告] 以下条目源文件缺失，未同步：{0}" -f ($missing -join ", "))
}
if ($mismatch.Count -gt 0) {
    Write-Host ("    [错误] 以下文件源/目标 SHA256 不一致，请检查磁盘：{0}" -f ($mismatch -join ", "))
}

if (($missing.Count -eq 0) -and ($mismatch.Count -eq 0)) {
    Write-Host "  [完成] 全部文件同步成功，源与目标 SHA256 一致。"
    Write-Host "  下一步：在 mac 上进入 mac打包文件夹 执行 build_mac.command。"
} elseif ($mismatch.Count -eq 0) {
    Write-Host "  [完成] 已同步，但有条目缺失（见上方警告），mac 打包前请补齐。"
} else {
    Write-Host "  [失败] 存在 SHA256 不一致的文件，请不要继续打包。"
}
Write-Host "=========================================================="
Write-Host ""

# ---- 同步后自动跑一次版本一致性检查（只读）----
$checkExit = $null
Write-Host "---- 自动运行 检查版本一致性.py ----"
if (Test-Path -LiteralPath $checker) {
    & python $checker
    $checkExit = $LASTEXITCODE
    if ($checkExit -ne 0) {
        Write-Host ("[注意] 检查版本一致性.py 返回 {0}，存在需要处理的问题（见上方输出）。" -f $checkExit)
    } else {
        Write-Host "[注意] 检查版本一致性.py 全部通过。"
    }
} else {
    Write-Host ("[警告] 找不到 {0}，跳过一致性检查。" -f $checker)
}
Write-Host ""

if ($mismatch.Count -gt 0) { exit 1 }
if (($null -ne $checkExit) -and ($checkExit -ne 0)) { exit 2 }
exit 0
