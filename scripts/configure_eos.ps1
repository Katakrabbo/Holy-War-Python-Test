param()

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SettingsPath = Join-Path $Root "multiplayer\eos.settings.json"

function Read-RequiredValue([string]$Label) {
    $Value = (Read-Host $Label).Trim()
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$Label non puo essere vuoto."
    }
    return $Value
}

$ProductId = Read-RequiredValue "Product ID"
$SandboxId = Read-RequiredValue "Sandbox ID"
$DeploymentId = Read-RequiredValue "Deployment ID"
$ClientId = Read-RequiredValue "Client ID"
$SecureSecret = Read-Host "Client Secret (non verra mostrato)" -AsSecureString
$SecretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureSecret)
try {
    $ClientSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($SecretPointer)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($SecretPointer)
}
if ([string]::IsNullOrWhiteSpace($ClientSecret)) { throw "Client Secret non puo essere vuoto." }

$Settings = [ordered]@{
    productId = $ProductId
    sandboxId = $SandboxId
    deploymentId = $DeploymentId
    clientId = $ClientId
    clientSecret = $ClientSecret
    encryptionKey = ""
    environment = "Development"
}
$Settings | ConvertTo-Json | Set-Content -LiteralPath $SettingsPath -Encoding UTF8
Write-Host "Configurazione EOS salvata localmente in $SettingsPath" -ForegroundColor Green
