$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$atlasPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$taskName = "Project Atlas Holdings Research"

if (-not (Test-Path -LiteralPath $atlasPython)) {
    throw "Atlas Python was not found at $atlasPython."
}

$action = New-ScheduledTaskAction `
    -Execute $atlasPython `
    -Argument "-m core.jobs.research_worker" `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes 30)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 55)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Checks Atlas every 30 minutes and refreshes saved holdings when the configured research interval is due." `
    -Force | Out-Null

Write-Host "Installed: $taskName"
Write-Host "Atlas will check every 30 minutes and refresh holdings only when the saved schedule is due."