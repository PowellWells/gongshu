[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$SkipSimulation,
    [ValidateRange(1, 65535)]
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendRoot = Join-Path $projectRoot "frontend"
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$appPath = Join-Path $projectRoot "run_vision2grasp_app.py"
$baseUrl = "http://127.0.0.1:$Port/"
$healthUrl = "${baseUrl}api/health"
$workbenchUrl = "${baseUrl}apps/gongshu/index.html"

function Get-AppHealth {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1
        if (
            $response.schema_version -eq "vision2grasp.app-health/v1" -and
            $response.status -eq "ok" -and
            $response.capabilities -contains "camera.phone-lan/v1"
        ) {
            return $response
        }
    }
    catch {
        return $null
    }
    return $null
}

function Stop-LegacyVision2GraspServer {
    $listener = Get-NetTCPConnection `
        -State Listen `
        -LocalPort $Port `
        -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $listener) {
        return $false
    }

    $process = Get-CimInstance Win32_Process `
        -Filter "ProcessId = $($listener.OwningProcess)"
    $commandLine = [string]$process.CommandLine
    $isLegacyServer = (
        $commandLine -like "*http.server*$Port*" -and
        $commandLine -like "*Vision2Grasp*frontend*"
    )
    $escapedProjectRoot = [WildcardPattern]::Escape($projectRoot)
    $isPreviousProjectServer = (
        $commandLine -like "*$escapedProjectRoot*run_vision2grasp_app.py*"
    )
    if (-not $isLegacyServer -and -not $isPreviousProjectServer) {
        throw "Port $Port is already used by another application: $commandLine"
    }

    Write-Host "Replacing the previous Vision2Grasp local server..."
    Stop-Process -Id $listener.OwningProcess -Force
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 150
        if (-not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)) {
            return $true
        }
    }
    throw "The previous Vision2Grasp server did not release port $Port."
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Project Python was not found: $pythonPath"
}
if (-not (Test-Path -LiteralPath $appPath -PathType Leaf)) {
    throw "Unified app entry was not found: $appPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "index.html") -PathType Leaf)) {
    throw "Frontend entry was not found: $frontendRoot\index.html"
}

$health = Get-AppHealth
if ($null -eq $health) {
    Stop-LegacyVision2GraspServer | Out-Null
    $arguments = "`"$appPath`" --host 127.0.0.1 --port $Port --no-browser"
    $appProcess = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList $arguments `
        -WindowStyle Minimized `
        -PassThru

    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 250
        if ($appProcess.HasExited) {
            throw "The Vision2Grasp app exited before it was ready."
        }
        if ($null -ne (Get-AppHealth)) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        if (-not $appProcess.HasExited) {
            Stop-Process -Id $appProcess.Id -Force
        }
        throw "The Vision2Grasp app did not become ready within 15 seconds. Check ports 8765-8767 and artifacts/launcher logs."
    }
    Write-Host "Vision2Grasp real-world-first app started at $workbenchUrl"
}
else {
    Write-Host "Vision2Grasp app is already running at $workbenchUrl"
}

if (-not $NoBrowser) {
    $cacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    Start-Process "${workbenchUrl}?open=$cacheBust"
}
