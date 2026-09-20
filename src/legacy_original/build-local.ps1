[CmdletBinding()]
param(
    [switch]$Install,
    [string]$OriginalExe = "$env:LOCALAPPDATA\Temp\eryou-mabao-re-20260814\mabao.exe",
    [string]$OriginalRuntime = 'C:\Program Files (x86)\LanRenMaBao\_internal',
    [string]$InstallRoot = "$env:LOCALAPPDATA\Programs\MabaoLocal"
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$extractor = Join-Path $PSScriptRoot 'tools\extract_original.py'
$abiSmoke = Join-Path $PSScriptRoot 'tools\abi_smoke.py'
$legacyLib = Join-Path $projectRoot 'build\legacy-original\legacy_lib'
$distRoot = Join-Path $projectRoot 'dist'
$bundleRoot = Join-Path $distRoot '二游辅助'
$spec = Join-Path $PSScriptRoot 'packaging\mabao_local.spec'
$iconPath = Join-Path $projectRoot 'assets\eryou_assistant_icon.ico'
$guestScript = Join-Path $PSScriptRoot 'bili_guest_hd.user.js'
$guestLicense = Join-Path $PSScriptRoot 'bili_guest_hd.LICENSE'
$helperSpec = Join-Path $PSScriptRoot 'packaging\game_input_helper.spec'
$helperDist = Join-Path $projectRoot 'build\legacy-original\helper-dist'
$helperOutput = Join-Path $helperDist 'mabao-game-input-helper.exe'
$venvSitePackages = Join-Path $projectRoot '.venv\Lib\site-packages'
$compatibleCv2 = Join-Path $venvSitePackages 'cv2'
$compatibleFfmpeg = Join-Path $compatibleCv2 'opencv_videoio_ffmpeg4140_64.dll'
$compatibleNumpy = Join-Path $venvSitePackages 'numpy'
$compatibleNumpyLibs = Join-Path $venvSitePackages 'numpy.libs'
$compatibleOnnxruntime = Join-Path $venvSitePackages 'onnxruntime'
$systemRuntime = Join-Path $env:SystemRoot 'System32'
$pythonBase = (& $python -c "import sys; print(sys.base_prefix)").Trim()
$compatibleRuntimeFiles = @{
    'MSVCP140.dll' = Join-Path $systemRuntime 'MSVCP140.dll'
    'MSVCP140_1.dll' = Join-Path $systemRuntime 'MSVCP140_1.dll'
    'VCRUNTIME140.dll' = Join-Path $pythonBase 'vcruntime140.dll'
    'VCRUNTIME140_1.dll' = Join-Path $pythonBase 'vcruntime140_1.dll'
    'ucrtbase.dll' = Join-Path $systemRuntime 'ucrtbase.dll'
}
$expectedOriginalSha256 = '3E1E2181D967650646FF8739C9CEF8D4F74E0C6BA5610676794530DE968EBD1D'

foreach ($required in @(
        $python,
        $OriginalExe,
        $OriginalRuntime,
        $extractor,
        $abiSmoke,
        $spec,
        $helperSpec,
        $iconPath,
        $guestScript,
        $guestLicense
    )) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing required input: $required"
    }
}
foreach ($entry in $compatibleRuntimeFiles.GetEnumerator()) {
    if (-not (Test-Path -LiteralPath $entry.Value -PathType Leaf)) {
        throw "Compatible runtime file is missing: $($entry.Value)"
    }
}

$actualOriginalSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $OriginalExe).Hash
if ($actualOriginalSha256 -ne $expectedOriginalSha256) {
    throw "Original executable hash mismatch: $actualOriginalSha256"
}

& $python $extractor $OriginalExe $legacyLib
if ($LASTEXITCODE -ne 0) { throw 'Original module extraction failed.' }

& $python -m PyInstaller --noconfirm --clean --distpath $distRoot `
    --workpath (Join-Path $projectRoot 'build\legacy-original\pyinstaller') $spec
if ($LASTEXITCODE -ne 0) { throw 'Local launcher build failed.' }

$helperSource = Join-Path $PSScriptRoot 'elevated_input_helper.py'
$helperNewestInput = @($helperSource, $helperSpec) |
    ForEach-Object { (Get-Item -LiteralPath $_).LastWriteTimeUtc } |
    Sort-Object -Descending | Select-Object -First 1
if (-not (Test-Path -LiteralPath $helperOutput) -or
    (Get-Item -LiteralPath $helperOutput).LastWriteTimeUtc -lt $helperNewestInput) {
    & $python -m PyInstaller --noconfirm --clean --distpath $helperDist `
        --workpath (Join-Path $projectRoot 'build\legacy-original\helper-pyinstaller') $helperSpec
    if ($LASTEXITCODE -ne 0) { throw 'Elevated input helper build failed.' }
}
Copy-Item -LiteralPath $helperOutput `
    -Destination (Join-Path $bundleRoot 'mabao-game-input-helper.exe') -Force

$targetInternal = Join-Path $bundleRoot '_internal'
if (Test-Path -LiteralPath $targetInternal) {
    # PyInstaller keeps stale files in an existing onedir output.  Reusing that
    # directory can silently mix old NumPy/OpenCV/ORT ABIs into the new build.
    Remove-Item -LiteralPath $targetInternal -Recurse -Force
}
New-Item -ItemType Directory -Path $targetInternal -Force | Out-Null
robocopy $OriginalRuntime $targetInternal /E /R:1 /W:1 `
    /XF 'cublas*.dll' 'cud*.dll' 'cufft*.dll' | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Runtime copy failed with robocopy code $LASTEXITCODE." }
robocopy $legacyLib $targetInternal /E /R:1 /W:1 | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Original PYZ merge failed with robocopy code $LASTEXITCODE." }
$runtimeAssets = @{
    'bili_guest_hd.user.js' = $guestScript
    'bili_guest_hd.LICENSE' = $guestLicense
    'eryou_assistant_icon.ico' = $iconPath
}
foreach ($entry in $runtimeAssets.GetEnumerator()) {
    Copy-Item -LiteralPath $entry.Value -Destination (Join-Path $targetInternal $entry.Key) -Force
}
$runtimeDirectories = @(
    $targetInternal
    Get-ChildItem -LiteralPath $targetInternal -Recurse -File |
        Where-Object { $_.Name -in $compatibleRuntimeFiles.Keys } |
        Select-Object -ExpandProperty DirectoryName
) | Sort-Object -Unique
foreach ($directory in $runtimeDirectories) {
    foreach ($entry in $compatibleRuntimeFiles.GetEnumerator()) {
        $target = Join-Path $directory $entry.Key
        if (Test-Path -LiteralPath $target -PathType Leaf) {
            Copy-Item -LiteralPath $entry.Value -Destination $target -Force
        }
    }
}
if (-not (Test-Path -LiteralPath $compatibleCv2) -or
    -not (Test-Path -LiteralPath $compatibleFfmpeg) -or
    -not (Test-Path -LiteralPath $compatibleNumpy) -or
    -not (Test-Path -LiteralPath $compatibleNumpyLibs) -or
    -not (Test-Path -LiteralPath $compatibleOnnxruntime)) {
    throw 'Compatible NumPy/OpenCV runtime is missing from the local virtual environment.'
}
$targetCv2 = Join-Path $targetInternal 'cv2'
$targetNumpy = Join-Path $targetInternal 'numpy'
$targetNumpyLibs = Join-Path $targetInternal 'numpy.libs'
$targetOnnxruntime = Join-Path $targetInternal 'onnxruntime'
$originalModuleCount = @(Get-ChildItem -LiteralPath $legacyLib -Recurse -File -Filter '*.pyc').Count
$originalNumpyPycCount = @(Get-ChildItem -LiteralPath (Join-Path $legacyLib 'numpy') -Recurse -File -Filter '*.pyc').Count
$compatibleNumpyPycCount = @(Get-ChildItem -LiteralPath $compatibleNumpy -Recurse -File -Filter '*.pyc').Count
foreach ($staleDirectory in @($targetCv2, $targetNumpyLibs)) {
    if (Test-Path -LiteralPath $staleDirectory) {
        Remove-Item -LiteralPath $staleDirectory -Recurse -Force
    }
}
Get-ChildItem -LiteralPath $targetInternal -File -Filter 'opencv_videoio_ffmpeg*.dll' -ErrorAction SilentlyContinue |
    Remove-Item -Force
robocopy $compatibleCv2 $targetCv2 /E /R:1 /W:1 /XF '*.pyc' | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Compatible OpenCV copy failed with robocopy code $LASTEXITCODE." }
Copy-Item -LiteralPath $compatibleFfmpeg -Destination $targetCv2 -Force
Get-ChildItem -LiteralPath $targetNumpy -Recurse -File -Filter '*.pyd' -ErrorAction SilentlyContinue |
    Remove-Item -Force
Get-ChildItem -LiteralPath $targetNumpy -Recurse -File -Filter '*.pyc' -ErrorAction SilentlyContinue |
    Remove-Item -Force
robocopy $compatibleNumpy $targetNumpy /E /R:1 /W:1 /XF '*.pyi' | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Compatible NumPy copy failed with robocopy code $LASTEXITCODE." }
robocopy $compatibleNumpyLibs $targetNumpyLibs /E /R:1 /W:1 | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Compatible NumPy DLL copy failed with robocopy code $LASTEXITCODE." }
Get-ChildItem -LiteralPath $targetOnnxruntime -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -in '.pyd', '.dll' } |
    Remove-Item -Force
robocopy $compatibleOnnxruntime $targetOnnxruntime /E /R:1 /W:1 /XF '*.pyc' | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Compatible ONNX Runtime copy failed with robocopy code $LASTEXITCODE." }
$multiarrayFiles = @(Get-ChildItem -LiteralPath $targetNumpy -Recurse -File -Filter '*multiarray_umath*.pyd')
if ($multiarrayFiles.Count -ne 1 -or $multiarrayFiles[0].FullName -match '\\numpy\\core\\') {
    throw "NumPy ABI inventory mismatch: $($multiarrayFiles.FullName -join ', ')"
}
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'overrides\app\particle_splash.py') `
    -Destination (Join-Path $targetInternal 'app\particle_splash.py') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'overrides\app\dialogs\auth_dialogs.py') `
    -Destination (Join-Path $targetInternal 'app\dialogs\auth_dialogs.py') -Force

$requiredModules = @(
    'app\main_window.pyc',
    'app\logger.pyc',
    'logger.pyc',
    'app\direction_reminder.pyc',
    'app\enhanced_reminder.pyc',
    'app\subtitle_parser.pyc',
    'app\subtitle_sprite.pyc',
    'app\turn_reminder.pyc',
    'app\hotkey_manager.pyc',
    'app\bookmark_manager.pyc',
    'app\history_manager.pyc',
    'app\theme\theme_manager.pyc',
    'app\immersive_anti_occlude.pyc',
    'app\immersive_dodge.pyc',
    'app\immersive_hole.pyc',
    'app\auto_dialog\manager.pyc',
    'app\auto_dialog\learning_window.pyc',
    'app\auto_dialog\runner.pyc',
    'app\auto_dialog\template_match.pyc',
    'app\ai_nav\ai_nav_worker.pyc',
    'app\ai_nav\ai_region_selector.pyc',
    'app\ai_nav\locator.pyc',
    'app\webview_container.pyc'
)
foreach ($relative in $requiredModules) {
    if (-not (Test-Path -LiteralPath (Join-Path $targetInternal $relative))) {
        throw "Missing extracted original module: $relative"
    }
}
$moduleCount = @(Get-ChildItem -LiteralPath $targetInternal -Recurse -File -Filter '*.pyc').Count
$appModuleCount = @(Get-ChildItem -LiteralPath (Join-Path $targetInternal 'app') -Recurse -File -Filter '*.pyc').Count
$expectedModuleCount = $originalModuleCount - $originalNumpyPycCount + $compatibleNumpyPycCount
if ($moduleCount -ne $expectedModuleCount -or $appModuleCount -ne 53) {
    throw "Original module inventory mismatch: total=$moduleCount expected=$expectedModuleCount app=$appModuleCount"
}
$namespacePackages = @(
    'mpl_toolkits',
    'pywin32_system32',
    'scipy\sparse\linalg\_propack',
    'scipy\stats\tests\data'
)
foreach ($relative in $namespacePackages) {
    $namespace = Join-Path $targetInternal $relative
    if (-not (Test-Path -LiteralPath $namespace -PathType Container) -or
        (Test-Path -LiteralPath (Join-Path $namespace '__init__.pyc'))) {
        throw "Invalid namespace package extraction: $relative"
    }
}
$forbiddenModules = @('app\auth.pyc', 'app\dialogs\auth_dialogs.pyc', 'tiandun.pyc', 'app\particle_splash.pyc')
foreach ($relative in $forbiddenModules) {
    if (Test-Path -LiteralPath (Join-Path $targetInternal $relative)) {
        throw "Removed legacy module leaked into bundle: $relative"
    }
}

if (-not $Install) {
    Write-Output $bundleRoot
    return
}

$localPrograms = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs'))
$resolvedInstall = [IO.Path]::GetFullPath($InstallRoot)
if (-not $resolvedInstall.StartsWith($localPrograms.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'InstallRoot must stay under LocalAppData Programs.'
}
if ($resolvedInstall -match '[^\u0000-\u007F]') {
    throw 'InstallRoot must be ASCII so ONNX Runtime can load model paths on Windows.'
}
$stage = "$resolvedInstall.stage-$PID"
$backup = "$resolvedInstall.previous"
if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
Copy-Item -LiteralPath $bundleRoot -Destination $stage -Recurse
$stageInternal = Join-Path $stage '_internal'
& $python -S $abiSmoke $stageInternal
$abiExitCode = $LASTEXITCODE
if ($abiExitCode -ne 0) { throw 'Bundled NumPy/OpenCV/ONNX Runtime ABI smoke test failed.' }
if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
if (Test-Path -LiteralPath $resolvedInstall) { Move-Item $resolvedInstall $backup }
try {
    Move-Item $stage $resolvedInstall
} catch {
    if (Test-Path -LiteralPath $backup) { Move-Item $backup $resolvedInstall }
    throw
}

$shortcutPath = Join-Path ([Environment]::GetFolderPath('Programs')) '二游辅助.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $resolvedInstall '二游辅助.exe'
$shortcut.WorkingDirectory = $resolvedInstall
$shortcut.Description = '二游辅助 - 免费开源本地版'
$shortcut.Save()
Write-Output $resolvedInstall
