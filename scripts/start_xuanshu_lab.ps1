[CmdletBinding()]
param(
    [switch]$Wait
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonwPath = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$entryPath = Join-Path $projectRoot "run_xuanshu_lab.py"
$vlmServerPath = Join-Path $projectRoot "artifacts\llama.cpp\b11424\llama-server.exe"
$vlmModelPath = Join-Path $projectRoot "artifacts\models\qwen3-vl-4b-instruct-gguf\Qwen3VL-4B-Instruct-Q4_K_M.gguf"
$vlmMmprojPath = Join-Path $projectRoot "artifacts\models\qwen3-vl-4b-instruct-gguf\mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf"
$defaultXiezhiFolder = -join ([char]0x4E94, [char]0x6708, [char]0x82B1)
$xiezhiRoot = if ($env:XIEZHI_PROJECT_ROOT) {
    $env:XIEZHI_PROJECT_ROOT
} elseif (Test-Path -LiteralPath "F:\" -PathType Container) {
    Join-Path "F:\" $defaultXiezhiFolder
} else {
    $null
}
$xiezhiSrc = if ($xiezhiRoot) { Join-Path $xiezhiRoot "src" } else { $null }

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
$xiezhiSourceAvailable = $false
if ($xiezhiSrc) {
    $xiezhiSourceAvailable = Test-Path `
        -LiteralPath (Join-Path $xiezhiSrc "xiezhi\__init__.py") `
        -PathType Leaf
}
if ($xiezhiSourceAvailable) {
    $pythonPathEntries += $xiezhiSrc
} else {
    $xiezhiDisplayPath = if ($xiezhiSrc) { $xiezhiSrc } else { "external Xiezhi project path not configured" }
    Write-Warning "Gongshu internal intelligence runtime was not found; core robot capabilities remain available: $xiezhiDisplayPath"
}
if ($env:PYTHONPATH) {
    $pythonPathEntries += $env:PYTHONPATH
}
$env:PYTHONPATH = $pythonPathEntries -join [IO.Path]::PathSeparator
$env:XIEZHI_ENABLED = "1"
$env:VISION2GRASP_VLM_REQUIRED = "1"

$vlmAssetSpecs = @(
    @{ Path = $vlmServerPath; MinimumBytes = 1 },
    @{ Path = $vlmModelPath; MinimumBytes = 2497281664 },
    @{ Path = $vlmMmprojPath; MinimumBytes = 453974304 }
)
foreach ($vlmAsset in $vlmAssetSpecs) {
    if (-not (Test-Path -LiteralPath $vlmAsset.Path -PathType Leaf) -or (Get-Item -LiteralPath $vlmAsset.Path).Length -lt $vlmAsset.MinimumBytes) {
        throw "Local VLM asset is missing or incomplete: $($vlmAsset.Path). Download the approved local Qwen3-VL GGUF assets before starting Gongshu."
    }
}
Write-Host "Local VLM assets verified: Qwen3-VL-4B-Instruct GGUF + llama.cpp CUDA runtime."

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
