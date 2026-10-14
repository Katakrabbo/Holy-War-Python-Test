param(
    [string]$Version = "0.1.0",
    [switch]$SkipPyInstaller
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    throw "Python venv non trovato: $PythonExe"
}

if (-not $SkipPyInstaller) {
    & $PythonExe -m pip install --upgrade pip pyinstaller

    if (Test-Path "build") {
        Remove-Item -LiteralPath "build" -Recurse -Force
    }
    if (Test-Path "dist\HolyWar") {
        Remove-Item -LiteralPath "dist\HolyWar" -Recurse -Force
    }

    & $PythonExe -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name HolyWar `
        --collect-submodules holywar.effects.card_scripts.cards `
        --add-data "holywar\data\cards.json;holywar\data" `
        --add-data "holywar\data\premade_decks.json;holywar\data" `
        --add-data "web_concept;web_concept" `
        holywar\web.py
}

$InnoCandidates = @(
    @(
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path $_) }
)

if (-not $InnoCandidates -or $InnoCandidates.Count -eq 0) {
    throw "ISCC.exe non trovato. Installa Inno Setup 6."
}

$IsccExe = $InnoCandidates[0]
& $IsccExe "/DAppVersion=$Version" "installer\HolyWar.iss"

Write-Host "Installer creato in: installer\dist"
