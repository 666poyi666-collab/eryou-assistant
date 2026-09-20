[CmdletBinding()]
param(
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\二游辅助')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$resolvedLocalPrograms = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs'))
$resolvedInstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$expectedRoot = [IO.Path]::GetFullPath((Join-Path $resolvedLocalPrograms '二游辅助'))
if (-not $resolvedInstallRoot.Equals($expectedRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to uninstall an unexpected path: $resolvedInstallRoot"
}

$shortcutPath = Join-Path ([Environment]::GetFolderPath('Programs')) '二游辅助.lnk'
if (Test-Path -LiteralPath $shortcutPath) {
    Remove-Item -LiteralPath $shortcutPath -Force
}
if (Test-Path -LiteralPath $resolvedInstallRoot) {
    Remove-Item -LiteralPath $resolvedInstallRoot -Recurse -Force
}

Write-Output $resolvedInstallRoot
