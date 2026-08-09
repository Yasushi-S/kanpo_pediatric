#Requires -RunAsAdministrator
# PowerShell（管理者）で実行

$ruleName = "kanpo-pediatric-app-50005"
$port = 50005

netsh advfirewall firewall delete rule name="$ruleName" | Out-Null

netsh advfirewall firewall add rule `
    name="$ruleName" `
    dir=in `
    action=allow `
    protocol=TCP `
    localport=$port

Write-Host "ファイアウォールルール '$ruleName' を設定しました。"
Write-Host "院内の他のPCから http://<このPCのIPアドレス>:$port にアクセスできます。"
Write-Host "このPCのIPアドレス確認: ipconfig"
