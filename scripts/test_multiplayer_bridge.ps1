param(
    [switch]$Release
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DotNet = Join-Path $Root ".tools\dotnet\dotnet.exe"
$Project = Join-Path $Root "multiplayer\HolyWar.Multiplayer.Bridge\HolyWar.Multiplayer.Bridge.csproj"
$Configuration = if ($Release) { "Release" } else { "Debug" }

if (-not (Test-Path -LiteralPath $DotNet)) {
    throw "SDK .NET locale non trovato. Esegui prima scripts\setup_multiplayer_dev.ps1."
}

& $DotNet build $Project --configuration $Configuration -p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw "Build del bridge multiplayer non riuscita." }

$BridgeDll = Join-Path (Split-Path $Project) "bin\x64\$Configuration\net8.0\HolyWar.Multiplayer.Bridge.dll"
& $DotNet $BridgeDll --self-test
if ($LASTEXITCODE -ne 0) { throw "Self-test del bridge multiplayer non riuscito." }

$Commands = @(
    '{"protocolVersion":1,"requestId":"1","operation":"initialize","payload":{}}'
    '{"protocolVersion":1,"requestId":"2","operation":"login","payload":{"displayName":"integration-test"}}'
    '{"protocolVersion":1,"requestId":"3","operation":"create_lobby","payload":{}}'
    '{"protocolVersion":1,"requestId":"4","operation":"send_packet","payload":{"data":"hello-holy-war"}}'
    '{"protocolVersion":1,"requestId":"5","operation":"shutdown","payload":{}}'
)
$Output = $Commands | & $DotNet $BridgeDll
if ($LASTEXITCODE -ne 0) { throw "Test JSON Lines del bridge non riuscito." }
$Messages = @($Output | ForEach-Object { $_ | ConvertFrom-Json })
$Responses = @($Messages | Where-Object { $_.type -eq "response" })
$Packet = @($Messages | Where-Object { $_.type -eq "packet_received" })
if ($Responses.Count -ne 5 -or @($Responses | Where-Object { -not $_.ok }).Count -ne 0) {
    throw "Il bridge non ha risposto correttamente a tutti i comandi."
}
if ($Packet.Count -ne 1 -or $Packet[0].payload.data -ne "hello-holy-war") {
    throw "Il bridge non ha restituito correttamente l'evento packet_received."
}

Write-Host "Bridge multiplayer C# verificato." -ForegroundColor Green
