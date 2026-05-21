[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Config,

    [string]$UpdateLog,
    [string]$PromoteCommit,
    [string]$PromoteSourceFingerprint,
    [string]$PromoteReportHash,

    [switch]$NoGitPull,
    [switch]$Verbose,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-RequiredValueFromLog {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$LogLines,

        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $pattern = [regex]::Escape($Label) + '\s*(.+)$'
    foreach ($line in $LogLines) {
        $match = [regex]::Match($line, $pattern)
        if ($match.Success) {
            $value = $match.Groups[1].Value.Trim()
            if ($value) {
                return $value
            }
        }
    }

    throw "Could not find '$Label' in update log."
}

function Resolve-UpdateLogPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ConfigPath,

        [string]$ExplicitLogPath
    )

    if ($ExplicitLogPath) {
        if (-not (Test-Path -LiteralPath $ExplicitLogPath)) {
            throw "Update log not found: $ExplicitLogPath"
        }
        return (Resolve-Path -LiteralPath $ExplicitLogPath).Path
    }

    $configPayload = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $configPayload.paths.root) {
        throw "project.json does not contain paths.root: $ConfigPath"
    }

    $logsRoot = Join-Path $configPayload.paths.root "logs"
    if (-not (Test-Path -LiteralPath $logsRoot)) {
        throw "Logs directory not found: $logsRoot"
    }

    $latestLog = Get-ChildItem -LiteralPath $logsRoot -File -Filter "*-update.log" |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1

    if (-not $latestLog) {
        throw "No *-update.log files found in: $logsRoot"
    }

    return $latestLog.FullName
}

$resolvedConfig = (Resolve-Path -LiteralPath $Config).Path
$resolvedUpdateLog = Resolve-UpdateLogPath -ConfigPath $resolvedConfig -ExplicitLogPath $UpdateLog
$logLines = Get-Content -LiteralPath $resolvedUpdateLog -Encoding UTF8

if (-not $PromoteCommit) {
    $PromoteCommit = Get-RequiredValueFromLog -LogLines $logLines -Label "Target commit:"
}

if (-not $PromoteSourceFingerprint) {
    $PromoteSourceFingerprint = Get-RequiredValueFromLog -LogLines $logLines -Label "Source fingerprint:"
}

if (-not $PromoteReportHash) {
    $PromoteReportHash = Get-RequiredValueFromLog -LogLines $logLines -Label "Report hash:"
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $scriptDir "update_mcp_project.py"

$arguments = @(
    $pythonScript,
    "--config", $resolvedConfig,
    "--promote-existing-build",
    "--promote-commit", $PromoteCommit,
    "--promote-source-fingerprint", $PromoteSourceFingerprint,
    "--promote-report-hash", $PromoteReportHash
)

if ($NoGitPull) {
    $arguments += "--no-git-pull"
}

if ($Verbose) {
    $arguments += "--verbose"
}

if ($DryRun) {
    $arguments += "--dry-run"
}

Write-Host "Using update log: $resolvedUpdateLog"
Write-Host "Promote commit: $PromoteCommit"
Write-Host "Promote source fingerprint: $PromoteSourceFingerprint"
Write-Host "Promote report hash: $PromoteReportHash"

& python @arguments
exit $LASTEXITCODE
