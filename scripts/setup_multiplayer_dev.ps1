param(
    [string]$Channel = "8.0"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$InstallDir = Join-Path $Root ".tools\dotnet"
$Installer = Join-Path $env:TEMP "holywar-dotnet-install.ps1"

if (Test-Path -LiteralPath (Join-Path $InstallDir "dotnet.exe")) {
    Write-Host "SDK .NET locale gia disponibile: $InstallDir"
    exit 0
}

Invoke-WebRequest -Uri "https://dot.net/v1/dotnet-install.ps1" -OutFile $Installer -UseBasicParsing
& $Installer -Channel $Channel -InstallDir $InstallDir -NoPath
if ($LASTEXITCODE -ne 0) { throw "Installazione SDK .NET non riuscita." }

Write-Host "SDK .NET installato localmente in: $InstallDir" -ForegroundColor Green
