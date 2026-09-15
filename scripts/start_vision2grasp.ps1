[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$SkipSimulation,
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [switch]$Wait
)

$ErrorActionPreference = "Stop"

$officialLauncher = Join-Path $PSScriptRoot "start_xuanshu_lab.ps1"
if (-not (Test-Path -LiteralPath $officialLauncher -PathType Leaf)) {
    throw "XUANSHU AI official launcher was not found: $officialLauncher"
}

Write-Warning "start_vision2grasp.ps1 is a compatibility wrapper. The official entry is G:\Vision2Grasp\Start-XUANSHU-LAB.cmd."
if ($NoBrowser -or $SkipSimulation -or $PSBoundParameters.ContainsKey("Port")) {
    Write-Warning "Legacy launcher options are ignored because XUANSHU AI Launcher owns module startup."
}

if ($Wait) {
    & $officialLauncher -Wait
} else {
    & $officialLauncher
}

exit $LASTEXITCODE
