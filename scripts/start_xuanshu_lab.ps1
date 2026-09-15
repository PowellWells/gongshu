[CmdletBinding()]
param(
    [switch]$Wait
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonwPath = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$entryPath = Join-Path $projectRoot "run_xuanshu_lab.py"
$defaultXiezhiFolder = -join ([char]0x4E94, [char]0x6708, [char]0x82B1)
$xiezhiRoot = if ($env:XIEZHI_PROJECT_ROOT) {
    $env:XIEZHI_PROJECT_ROOT
} else {
    Join-Path "F:\" $defaultXiezhiFolder
}
$xiezhiSrc = Join-Path $xiezhiRoot "src"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Project Python was not found: $pythonPath"
}
if (-not (Test-Path -LiteralPath $pythonwPath -PathType Leaf)) {
    throw "Project Python windowed launcher was not found: $pythonwPath"
}
if (-not (Test-Path -LiteralPath $entryPath -PathType Leaf)) {
    throw "XUANSHU LAB entry was not found: $entryPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $xiezhiSrc "xiezhi\__init__.py") -PathType Leaf)) {
    throw "Xiezhi runtime was not found: $xiezhiSrc"
}

$pythonPathEntries = @((Join-Path $projectRoot "src"), $xiezhiSrc)
if ($env:PYTHONPATH) {
    $pythonPathEntries += $env:PYTHONPATH
}
$env:PYTHONPATH = $pythonPathEntries -join [IO.Path]::PathSeparator
$env:XIEZHI_ENABLED = "1"

$pysideReady = & $pythonPath -c "import PySide6, PySide6.QtWebEngineWidgets"
if ($LASTEXITCODE -ne 0) {
    throw "PySide6 6.8.3 is not installed in the project environment. Run: .venv\Scripts\python.exe -m pip install -e ."
}

$xiezhiReady = & $pythonPath -c "from xiezhi.runtime import default_algorithm_registry; assert 'rule_based' in default_algorithm_registry().names()"
if ($LASTEXITCODE -ne 0) {
    throw "Xiezhi runtime or its rule_based policy could not be loaded from: $xiezhiSrc"
}

$arguments = "`"$entryPath`""
if ($Wait) {
    $process = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList $arguments `
        -WorkingDirectory $projectRoot `
        -PassThru `
        -Wait
    exit $process.ExitCode
}

Start-Process `
    -FilePath $pythonwPath `
    -ArgumentList $arguments `
    -WorkingDirectory $projectRoot

Write-Host "Gongshu is starting with the Xiezhi decision layer enabled."
