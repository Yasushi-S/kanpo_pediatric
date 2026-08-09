#Requires -RunAsAdministrator
# PowerShell（管理者）で実行
# 例: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass; .\setup_task_scheduler.ps1

$taskName = "kanpo-pediatric-app"
$repoRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$batPath = Join-Path $repoRoot "start_app.bat"

if (-not (Test-Path -LiteralPath $batPath)) {
    Write-Error "start_app.bat が見つかりません: $batPath"
    exit 1
}

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$batPath`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force

Write-Host "タスク '$taskName' を登録しました。"
Write-Host "PCを再起動すると自動起動します。"
Write-Host "手動テスト: Start-ScheduledTask -TaskName '$taskName'"
