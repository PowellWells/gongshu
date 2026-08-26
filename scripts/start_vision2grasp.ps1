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
$pipelinePath = Join-Path $projectRoot "run_bottle_pipeline.py"
$runtimeRoot = Join-Path $frontendRoot "runtime"
$runtimeRunsRoot = Join-Path $runtimeRoot "runs"
$manifestPath = Join-Path $runtimeRoot "latest.json"
$launcherLogRoot = Join-Path $projectRoot "artifacts\launcher"
$portalUrl = "http://127.0.0.1:$Port/"
$workbenchUrl = "${portalUrl}apps/gongshu/index.html"
$portalMarker = "XUANSHU AI"

function Get-PortalResponse {
    try {
        return Invoke-WebRequest -Uri $portalUrl -UseBasicParsing -TimeoutSec 1
    }
    catch {
        return $null
    }
}

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Project Python was not found: $pythonPath"
}

if (-not (Test-Path -LiteralPath (Join-Path $frontendRoot "index.html") -PathType Leaf)) {
    throw "Frontend entry was not found: $frontendRoot\index.html"
}

if (-not (Test-Path -LiteralPath $pipelinePath -PathType Leaf)) {
    throw "Bottle pipeline entry was not found: $pipelinePath"
}

$response = Get-PortalResponse
if ($null -ne $response) {
    if ($response.StatusCode -ne 200 -or $response.Content -notmatch [regex]::Escape($portalMarker)) {
        throw "Port $Port is already used by another application. Close it or run scripts\start_vision2grasp.ps1 -Port <port>."
    }
}

if (-not $SkipSimulation) {
    New-Item -ItemType Directory -Path $runtimeRunsRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $launcherLogRoot -Force | Out-Null

    $runId = "launcher-bottle-seed7-{0}" -f (Get-Date -Format "yyyyMMddTHHmmssfff")
    $runDirectory = Join-Path $runtimeRunsRoot $runId
    $runJsonPath = Join-Path $runDirectory "run.json"
    $stdoutLog = Join-Path $launcherLogRoot "latest.stdout.log"
    $stderrLog = Join-Path $launcherLogRoot "latest.stderr.log"
    $pipelineArguments = "`"$pipelinePath`" --output-root `"$runtimeRunsRoot`" --run-id `"$runId`""

    Write-Host "Running the Vision2Grasp bottle simulation..."
    $pipelineProcess = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList $pipelineArguments `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -Wait `
        -PassThru

    if (-not (Test-Path -LiteralPath $runJsonPath -PathType Leaf)) {
        throw "The simulation did not produce run.json. See $stderrLog"
    }

    try {
        $runJsonText = [System.IO.File]::ReadAllText($runJsonPath, [System.Text.Encoding]::UTF8)
        $runDocument = $runJsonText | ConvertFrom-Json
    }
    catch {
        throw "The simulation produced an invalid run.json. See $runJsonPath"
    }

    if ($runDocument.schema_version -ne "vision2grasp.run/v1") {
        throw "The simulation produced an unsupported run schema: $($runDocument.schema_version)"
    }

    $manifest = [ordered]@{
        schema_version = "vision2grasp.launcher/v1"
        run_json = "runs/$runId/run.json"
    } | ConvertTo-Json
    $temporaryManifest = Join-Path $runtimeRoot ("latest.{0}.tmp" -f [guid]::NewGuid().ToString("N"))
    [System.IO.File]::WriteAllText($temporaryManifest, $manifest, [System.Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporaryManifest -Destination $manifestPath -Force

    if ($pipelineProcess.ExitCode -eq 0) {
        Write-Host "Simulation completed successfully."
    }
    else {
        Write-Warning "The simulation completed but did not meet the isolated lift acceptance threshold. The public run result will still be displayed."
    }
}
elseif (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "No published run is available. Start once without -SkipSimulation."
}

if ($null -eq $response) {
    $serverArguments = "-m http.server $Port --bind 127.0.0.1 --directory `"$frontendRoot`""
    $serverProcess = Start-Process `
        -FilePath $pythonPath `
        -ArgumentList $serverArguments `
        -WindowStyle Minimized `
        -PassThru

    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250

        if ($serverProcess.HasExited) {
            throw "The local server exited before the portal was ready."
        }

        $response = Get-PortalResponse
        if ($null -ne $response -and $response.StatusCode -eq 200 -and $response.Content -match [regex]::Escape($portalMarker)) {
            $ready = $true
            break
        }
    }

    if (-not $ready) {
        if (-not $serverProcess.HasExited) {
            Stop-Process -Id $serverProcess.Id
        }
        throw "The portal did not become ready within 10 seconds."
    }

    Write-Host "Vision2Grasp started at $portalUrl"
}
else {
    Write-Host "Vision2Grasp is already running at $portalUrl"
}

if (-not $NoBrowser) {
    $cacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
    Start-Process "${workbenchUrl}?autoload=$cacheBust"
}
