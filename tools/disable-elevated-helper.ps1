# =====================================================================
#  关闭/删除「二游辅助」遗留的提权输入助手（MabaoLocalGameInput）
#
#  为什么需要：
#   老版本启动时会把 mabao-game-input-helper.exe 复制到
#   C:\Program Files\MabaoLocalInputHelper 并注册一个 ONLOGON + HIGHEST 的计划任务，
#   它以管理员身份跑全局键盘/鼠标低级钩子（WH_KEYBOARD_LL / WH_MOUSE_LL）。
#   这类提权全局钩子很容易被游戏反作弊判定为可疑（原神 mhyprot2 会直接结束游戏），
#   而新版已经把助手改成显式开关（环境变量 MABAO_ENABLE_ELEVATED_INPUT_HELPER=1
#   才启用），所以这个任务应该关掉。
#
#  必须以管理员运行（UAC 会弹一次）。
#
#  用法：
#    powershell -Verb RunAs -File tools\disable-elevated-helper.ps1            # 停+禁用+删除任务
#    powershell -Verb RunAs -File tools\disable-elevated-helper.ps1 -KeepFiles # 只停任务，保留文件
# =====================================================================
[CmdletBinding()]
param(
    [string]$TaskName = 'MabaoLocalGameInput',
    [string]$HelperDir = "$env:ProgramFiles\MabaoLocalInputHelper",
    [switch]$KeepFiles
)

$ErrorActionPreference = 'Continue'
$log = Join-Path $env:LOCALAPPDATA 'MabaoLocal\logs\disable-elevated-helper.log'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
function W($m) {
    $line = "[{0:HH:mm:ss}] {1}" -f (Get-Date), $m
    Write-Host $line
    Add-Content -LiteralPath $log -Value $line -Encoding UTF8
}

W '=== 关闭提权输入助手 ==='
W ("是否管理员: {0}" -f ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))

W '1) 结束正在运行的 helper 进程'
Get-Process -Name 'mabao-game-input-helper' -ErrorAction SilentlyContinue |
    ForEach-Object { W ("   结束 pid={0}" -f $_.Id); Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

W '2) 停止计划任务'
& schtasks /End /TN $TaskName 2>&1 | ForEach-Object { W "   $_" }

W '3) 禁用计划任务'
& schtasks /Change /TN $TaskName /DISABLE 2>&1 | ForEach-Object { W "   $_" }

W '4) 删除计划任务'
& schtasks /Delete /TN $TaskName /F 2>&1 | ForEach-Object { W "   $_" }
$deleted = -not (schtasks /Query /TN $TaskName 2>$null)
W ("   删除结果: {0}" -f $(if ($deleted) { '已删除' } else { '仍存在（需要管理员）' }))

if (-not $KeepFiles) {
    W '5) 移除 Program Files 里的 helper 副本'
    if (Test-Path -LiteralPath $HelperDir) {
        Remove-Item -LiteralPath $HelperDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    W ("   {0} 存在: {1}" -f $HelperDir, (Test-Path -LiteralPath $HelperDir))
}

W '=== 结果 ==='
$still = schtasks /Query /TN $TaskName /FO LIST 2>&1 | Select-String -Pattern 'TaskName|Status'
if ($still) { $still | ForEach-Object { W "   任务仍在: $($_.Line.Trim())" } } else { W '   任务已不存在 ✓' }
$procs = Get-Process -Name 'mabao-game-input-helper' -ErrorAction SilentlyContinue
if ($procs) { W ("   helper 进程仍在: {0}" -f ($procs.Id -join ',')) } else { W '   没有 helper 进程 ✓' }
W ("日志: {0}" -f $log)
