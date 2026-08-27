[CmdletBinding()]
param(
    [switch]$Wait
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonwPath = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$entryPath = Join-Path $projectRoot "run_xuanshu_lab.py"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Project Python was not found: $pythonPath"
}
if (-not (Test-Path -LiteralPath $pythonwPath -PathType Leaf)) {
    throw "Project Python windowed launcher was not found: $pythonwPath"
}
if (-not (Test-Path -LiteralPath $entryPath -PathType Leaf)) {
    throw "XUANSHU LAB entry was not found: $entryPath"
}

$pysideReady = & $pythonPath -c "import PySide6, PySide6.QtWebEngineWidgets"
if ($LASTEXITCODE -ne 0) {
    throw "PySide6 6.8.3 is not installed in the project environment. Run: .venv\Scripts\python.exe -m pip install -e ."
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

Write-Host "XUANSHU LAB is starting."
