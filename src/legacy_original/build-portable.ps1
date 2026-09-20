[CmdletBinding()]
<#
.SYNOPSIS
  从「已有一份能跑的便携包」重新构建 二游辅助.exe，并组装出新的便携包。

  原版 build-local.ps1 需要 C:\Program Files (x86)\LanRenMaBao 的原版运行时（本机已不存在）。
  这份脚本改用现有便携包的 _internal 作为依赖来源：只重编 EXE（launcher/local_features/
  borderless 这一层补丁），依赖（PyQt5/pythonnet/numpy/cv2/onnxruntime/app 字节码）原样复用，
  因此改源码后几十秒就能出一个新包，也能做 A/B 回滚。

.EXAMPLE
  powershell -File build-portable.ps1
  powershell -File build-portable.ps1 -Deploy        # 组装完原子替换 ..\app（旧包存 ..\app.previous）
#>
[CmdletBinding()]
param(
    [string]$SourceBundle = '',
    [string]$OutBundle = '',
    [string]$Python = '',
    [switch]$SkipBuild,
    [switch]$SkipOverrides,
    [switch]$Deploy
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$legacyRoot = $PSScriptRoot                                   # src/legacy_original
$repoRoot = Split-Path -Parent (Split-Path -Parent $legacyRoot)   # 03_二游辅助
if (-not $SourceBundle) { $SourceBundle = Join-Path $repoRoot 'app' }
if (-not $OutBundle) { $OutBundle = Join-Path $repoRoot 'build\out' }
if (-not $Python) { $Python = Join-Path $repoRoot 'build\venv\Scripts\python.exe' }
$spec = Join-Path $legacyRoot 'packaging\eryou_portable.spec'
$distExe = Join-Path $repoRoot 'build\dist\二游辅助\二游辅助.exe'
$inspector = Join-Path $repoRoot 'tools\inspect_pyz.py'
$overrideTool = Join-Path $repoRoot 'tools\apply_runtime_overrides.py'
$bomTool = Join-Path $repoRoot 'tools\ensure_bom.py'

foreach ($required in @($Python, $spec, $inspector, $overrideTool, $bomTool)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "缺少构建输入：$required" }
}
# 先确保含中文的 .ps1 都带 BOM（编辑工具会把 BOM 弄丢，5.1 会因此假语法报错）
& $Python $bomTool | Write-Host
$sourceInternal = Join-Path $SourceBundle '_internal'
if (-not (Test-Path -LiteralPath (Join-Path $sourceInternal 'app\main_window.pyc'))) {
    throw "SourceBundle 不像便携包（缺 _internal\app\main_window.pyc）：$SourceBundle"
}
Write-Host "[1/5] 依赖来源：$SourceBundle"

# 1) 用原版包的 PYZ 模块清单算出重建包需要补的 stdlib（漏了会让 XFeat 退回 ORB）
Write-Host '[2/5] 计算 stdlib 补齐清单…'
& $Python $inspector | Write-Host
if ($LASTEXITCODE -ne 0) { throw 'inspect_pyz.py 失败' }

# 2) 重新编译 EXE（含提权输入助手）
if (-not $SkipBuild) {
    Write-Host '[3/5] PyInstaller 重编 二游辅助.exe…'
    & $Python -m PyInstaller --noconfirm --clean `
        --distpath (Join-Path $repoRoot 'build\dist') `
        --workpath (Join-Path $repoRoot 'build\work') $spec | Select-Object -Last 3 | Write-Host
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 构建失败（主程序）' }

    # 提权助手必须跟着 elevated_input_helper.py 一起重编（它承担提权游戏下的快捷键）
    $helperSpec = Join-Path $legacyRoot 'packaging\game_input_helper.spec'
    if (Test-Path -LiteralPath $helperSpec) {
        Write-Host '[3/5] PyInstaller 重编 mabao-game-input-helper.exe…'
        & $Python -m PyInstaller --noconfirm --clean `
            --distpath (Join-Path $repoRoot 'build\helper-dist') `
            --workpath (Join-Path $repoRoot 'build\helper-work') $helperSpec | Select-Object -Last 2 | Write-Host
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 构建失败（提权助手）' }
    }
} else {
    Write-Host '[3/5] 跳过重编（-SkipBuild）'
}
if (-not (Test-Path -LiteralPath $distExe)) { throw "没有产出 EXE：$distExe" }

# 3) 组装：新 EXE + 依赖来源的 _internal + 新编/复制的 helper
Write-Host "[4/5] 组装到 $OutBundle …"
if (Test-Path -LiteralPath $OutBundle) { Remove-Item -LiteralPath $OutBundle -Recurse -Force }
New-Item -ItemType Directory -Path $OutBundle -Force | Out-Null
Copy-Item -LiteralPath $distExe -Destination (Join-Path $OutBundle '二游辅助.exe') -Force
$builtHelper = Join-Path $repoRoot 'build\helper-dist\mabao-game-input-helper.exe'
$helper = if (Test-Path -LiteralPath $builtHelper) { $builtHelper } else { Join-Path $SourceBundle 'mabao-game-input-helper.exe' }
if (Test-Path -LiteralPath $helper) {
    Copy-Item -LiteralPath $helper -Destination (Join-Path $OutBundle 'mabao-game-input-helper.exe') -Force
    Write-Host ("  helper 来源   = {0}" -f $helper)
}
robocopy $sourceInternal (Join-Path $OutBundle '_internal') /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制 _internal 失败（robocopy $LASTEXITCODE）" }

# 4) 铺运行时覆盖（qtwebview2/widget.py 等）
if (-not $SkipOverrides) {
    & $Python $overrideTool --bundle $OutBundle | Write-Host
    if ($LASTEXITCODE -ne 0) { throw '覆盖文件应用失败' }
}

# 5) 校验 + 报告
Write-Host '[5/5] 校验…'
$exePath = Join-Path $OutBundle '二游辅助.exe'
$exeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $exePath).Hash
$fileCount = @(Get-ChildItem -LiteralPath $OutBundle -Recurse -File).Count
Write-Host ("  新 EXE sha256 = {0}" -f $exeHash)
Write-Host ("  文件总数      = {0}" -f $fileCount)
Write-Host ("  依赖复用自    = {0}" -f $SourceBundle)
Write-Host ("  输出          = {0}" -f $OutBundle)

if ($Deploy) {
    $backup = "$SourceBundle.previous"
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
    if (Test-Path -LiteralPath $SourceBundle) { Move-Item -LiteralPath $SourceBundle -Destination $backup }
    try {
        Move-Item -LiteralPath $OutBundle -Destination $SourceBundle
        Write-Host "已部署：$SourceBundle（旧包在 $backup）"
    } catch {
        if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $SourceBundle }
        throw
    }
}
