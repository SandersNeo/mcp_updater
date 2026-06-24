[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Config,

    [switch]$Force,
    [switch]$StorageMigration,
    [switch]$NoGitPull,
    [switch]$Rollback,
    [switch]$DryRun
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $scriptDir "update_mcp_project.py"

$arguments = @($pythonScript, "--config", $Config)

if ($Force) {
    $arguments += "--force"
}

if ($StorageMigration) {
    $arguments += "--storage-migration"
}

if ($NoGitPull) {
    $arguments += "--no-git-pull"
}

if ($Rollback) {
    $arguments += "--rollback"
}

if ($PSBoundParameters.ContainsKey("Verbose")) {
    $arguments += "--verbose"
}

if ($DryRun) {
    $arguments += "--dry-run"
}

& python @arguments
exit $LASTEXITCODE
