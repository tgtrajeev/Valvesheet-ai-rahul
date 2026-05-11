param(
  [string]$Date = "today"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot "daily_report.py"

Set-Location $repoRoot

python $script --date $Date

