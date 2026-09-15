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
$pythonPathEntries = @((Join-Path $projectRoot "src"))
$xiezhiSourceAvailable = Test-Path `
    -LiteralPath (Join-Path $xiezhiSrc "xiezhi\__init__.py") `
    -PathType Leaf
if ($xiezhiSourceAvailable) {
    $pythonPathEntries += $xiezhiSrc
} else {
    Write-Warning "Gongshu internal intelligence runtime was not found; core robot capabilities remain available: $xiezhiSrc"
}
if ($env:PYTHONPATH) {
    $pythonPathEntries += $env:PYTHONPATH
}
$env:PYTHONPATH = $pythonPathEntries -join [IO.Path]::PathSeparator
$env:XIEZHI_ENABLED = "1"

$pysideReady = & $pythonPath -c "import PySide6, PySide6.QtWebEngineWidgets"
if ($LASTEXITCODE -ne 0) {
    throw "PySide6 6.8.3 is not installed in the project environment. Run: .venv\Scripts\python.exe -m pip install -e ."
}

if ($xiezhiSourceAvailable) {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $pythonPath -c "from xiezhi.runtime.lifecycle import XiezhiLifecycleRuntime; assert XiezhiLifecycleRuntime().status().connected" 2>$null
    $xiezhiReady = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $previousErrorActionPreference
    if (-not $xiezhiReady) {
        Write-Warning "Gongshu internal intelligence runtime is unavailable; core robot capabilities remain available."
    }
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

Write-Host "Gongshu is starting and will load its internal Xiezhi intelligence capability when available."
