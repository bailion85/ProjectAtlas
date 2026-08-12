$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$atlasPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$taskName = "Project Atlas Daily Discovery"

if (-not (Test-Path -LiteralPath $atlasPython)) {
    throw "Atlas Python was not found at $atlasPython."
}

$action = New-ScheduledTaskAction `
    -Execute $atlasPython `
    -Argument "-m core.jobs.discovery_worker" `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).Date.AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Minutes 30)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 25)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Checks the Project Atlas Discovery schedule and runs one cached market scan when due." `
    -Force | Out-Null

Write-Host "Installed: $taskName"
Write-Host "Atlas will check every 30 minutes and run only when the enabled Discovery schedule is due."
