[CmdletBinding()]
param(
    [switch]$Install,
    [switch]$WithAI,
    [switch]$SkipBuild,
    [string]$InstallRoot = (Join-Path $env:LOCALAPPDATA 'Programs\二游辅助')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$spec = Join-Path $projectRoot 'packaging\eryou_assistant.spec'
$distRoot = Join-Path $projectRoot 'dist'
$buildRoot = Join-Path $projectRoot 'build\pyinstaller'
$bundleRoot = Join-Path $distRoot '二游辅助'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Missing .venv. Install development dependencies before building.'
}

if (-not $SkipBuild) {
    if ($WithAI) {
        & $python -c 'import cv2, numpy, onnxruntime'
        if ($LASTEXITCODE -ne 0) {
            throw 'AI dependencies are missing. Install the ai optional dependencies first.'
        }
        $env:ERYOU_INCLUDE_AI = '1'
    } else {
        $env:ERYOU_INCLUDE_AI = '0'
    }

    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        --distpath $distRoot `
        --workpath $buildRoot `
        $spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
}

$executable = Join-Path $bundleRoot '二游辅助.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Build completed without the expected executable: $executable"
}

$requiredRuntimeFiles = @(
    '_internal\lib\Microsoft.Web.WebView2.Core.dll',
    '_internal\lib\Microsoft.Web.WebView2.WinForms.dll',
    '_internal\lib\runtimes\win-x64\native\WebView2Loader.dll',
    '_internal\pythonnet\runtime\Python.Runtime.dll',
    '_internal\clr_loader\ffi\dlls\amd64\ClrLoader.dll'
)
foreach ($relativePath in $requiredRuntimeFiles) {
    $runtimePath = Join-Path $bundleRoot $relativePath
    if (-not (Test-Path -LiteralPath $runtimePath -PathType Leaf)) {
        throw "Build completed without required WebView2 runtime support: $relativePath"
    }
}

if (-not $Install) {
    Write-Output $bundleRoot
    return
}

$resolvedLocalPrograms = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs'))
$resolvedInstallRoot = [IO.Path]::GetFullPath($InstallRoot)
$localPrefix = $resolvedLocalPrograms.TrimEnd('\') + '\'
if (-not $resolvedInstallRoot.StartsWith($localPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "InstallRoot must stay under the current user's LocalAppData Programs directory."
}

$stageRoot = "$resolvedInstallRoot.stage-$PID"
$backupRoot = "$resolvedInstallRoot.previous"
if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
Copy-Item -LiteralPath $bundleRoot -Destination $stageRoot -Recurse

if (Test-Path -LiteralPath $backupRoot) {
    Remove-Item -LiteralPath $backupRoot -Recurse -Force
}
if (Test-Path -LiteralPath $resolvedInstallRoot) {
    Move-Item -LiteralPath $resolvedInstallRoot -Destination $backupRoot
}

try {
    Move-Item -LiteralPath $stageRoot -Destination $resolvedInstallRoot
} catch {
    if (Test-Path -LiteralPath $backupRoot) {
        Move-Item -LiteralPath $backupRoot -Destination $resolvedInstallRoot
    }
    throw
}

$startMenu = [Environment]::GetFolderPath('Programs')
$shortcutPath = Join-Path $startMenu '二游辅助.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $resolvedInstallRoot '二游辅助.exe'
$shortcut.WorkingDirectory = $resolvedInstallRoot
$shortcut.Description = '二游辅助 - 免费开源本地版'
$shortcut.Save()

Write-Output $resolvedInstallRoot
