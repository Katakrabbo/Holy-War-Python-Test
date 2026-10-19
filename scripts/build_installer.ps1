param(
    [string]$Version = "0.2.0",
    [switch]$SkipPyInstaller,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$PythonExe = Join-Path $Root ".venv\Scripts\python.exe"
$PackagedExe = Join-Path $Root "dist\HolyWar\HolyWar.exe"
if (-not (Test-Path -LiteralPath $PythonExe)) {
    $PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $PythonLauncher) {
        throw "Python non trovato. Installa Python 3.11 o successivo sul PC usato per creare l'installer."
    }
    & $PythonLauncher.Source -3 -m venv (Join-Path $Root ".venv")
    if ($LASTEXITCODE -ne 0) {
        throw "Creazione dell'ambiente Python non riuscita (codice $LASTEXITCODE)."
    }
}

if (-not $SkipPyInstaller) {
    Write-Host "Installazione degli strumenti di build..."
    & $PythonExe -m pip install --upgrade pip "pyinstaller>=6.16" ".[dev]"
    if ($LASTEXITCODE -ne 0) {
        throw "Installazione delle dipendenze non riuscita (codice $LASTEXITCODE)."
    }

    if (-not $SkipTests) {
        Write-Host "Esecuzione dei test..."
        & $PythonExe -m pytest
        if ($LASTEXITCODE -ne 0) {
            throw "I test non sono riusciti. Installer non creato."
        }
    }

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
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller non e riuscito (codice $LASTEXITCODE)."
    }

    if (-not (Test-Path -LiteralPath $PackagedExe)) {
        throw "Eseguibile non trovato dopo il build: $PackagedExe"
    }

    Write-Host "Verifica dell'eseguibile senza Python o Node..."
    $Probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $Probe.Start()
    $SmokePort = ([System.Net.IPEndPoint]$Probe.LocalEndpoint).Port
    $Probe.Stop()
    $PackagedProcess = $null
    try {
        $PackagedProcess = Start-Process `
            -FilePath $PackagedExe `
            -ArgumentList @("--no-browser", "--port", "$SmokePort") `
            -WorkingDirectory (Split-Path $PackagedExe) `
            -WindowStyle Hidden `
            -PassThru
        $Healthy = $false
        for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
            if ($PackagedProcess.HasExited) {
                break
            }
            try {
                $Config = Invoke-RestMethod -Uri "http://127.0.0.1:$SmokePort/api/config" -TimeoutSec 1
                if ($Config.application -eq "holywar") {
                    $Healthy = $true
                    break
                }
            }
            catch {
                Start-Sleep -Milliseconds 250
            }
        }
        if (-not $Healthy) {
            $LogPath = Join-Path $env:APPDATA "HolyWar\startup_error.log"
            $LogHint = if (Test-Path -LiteralPath $LogPath) { " Controlla: $LogPath" } else { "" }
            throw "L'eseguibile creato non ha superato il test di avvio.$LogHint"
        }
    }
    finally {
        if ($PackagedProcess -and -not $PackagedProcess.HasExited) {
            Stop-Process -Id $PackagedProcess.Id -Force
            $PackagedProcess.WaitForExit()
        }
    }

    Write-Host "Verifica della finestra desktop WebView2..."
    $WindowSmoke = Start-Process `
        -FilePath $PackagedExe `
        -ArgumentList @("--smoke-window", "--port", "0") `
        -WorkingDirectory (Split-Path $PackagedExe) `
        -WindowStyle Hidden `
        -PassThru
    if (-not $WindowSmoke.WaitForExit(30000)) {
        Stop-Process -Id $WindowSmoke.Id -Force
        throw "La finestra desktop non ha completato il test entro 30 secondi."
    }
    if ($WindowSmoke.ExitCode -ne 0) {
        throw "La finestra desktop non ha superato il test (codice $($WindowSmoke.ExitCode))."
    }
}
elseif (-not (Test-Path -LiteralPath (Join-Path $Root "dist\HolyWar\HolyWar.exe"))) {
    throw "-SkipPyInstaller richiede dist\HolyWar\HolyWar.exe gia esistente."
}

$EosSdkSource = Join-Path $Root "multiplayer\eos-sdk\SDK\Source"
$EosNativeDll = Join-Path $Root "multiplayer\eos-sdk\SDK\Bin\EOSSDK-Win64-Shipping.dll"
$EosSettings = Join-Path $Root "multiplayer\eos.settings.json"
if (-not (Test-Path -LiteralPath $EosSdkSource)) {
    throw "SDK EOS C# non trovato. Estrai l'archivio con scripts\configure_eos.ps1."
}
if (-not (Test-Path -LiteralPath $EosNativeDll)) {
    throw "DLL nativa EOS x64 non trovata: $EosNativeDll"
}
if (-not (Test-Path -LiteralPath $EosSettings)) {
    throw "Credenziali EOS non configurate. Crea multiplayer\eos.settings.json."
}

$LocalDotnetExe = Join-Path $Root ".tools\dotnet\dotnet.exe"
$DotnetCommand = Get-Command dotnet -ErrorAction SilentlyContinue
$DotnetExe = if (Test-Path -LiteralPath $LocalDotnetExe) {
    $LocalDotnetExe
} elseif ($DotnetCommand) {
    $DotnetCommand.Source
} else {
    $LocalDotnetExe
}
if (-not (Test-Path -LiteralPath $DotnetExe)) {
    throw ".NET SDK non trovato. Esegui prima scripts\setup_multiplayer_dev.ps1."
}
$InstalledSdks = @(& $DotnetExe --list-sdks)
if ($LASTEXITCODE -ne 0 -or $InstalledSdks.Count -eq 0) {
    throw "Il comando dotnet trovato non contiene un SDK. Esegui scripts\setup_multiplayer_dev.ps1."
}

$BridgeProject = Join-Path $Root "multiplayer\HolyWar.Multiplayer.Bridge\HolyWar.Multiplayer.Bridge.csproj"
$BridgeOutput = Join-Path $Root "dist\HolyWar\multiplayer"
if (Test-Path -LiteralPath $BridgeOutput) {
    Remove-Item -LiteralPath $BridgeOutput -Recurse -Force
}
Write-Host "Pubblicazione del multiplayer EOS self-contained..."
& $DotnetExe publish $BridgeProject `
    --configuration Release `
    --runtime win-x64 `
    --self-contained true `
    -p:Platform=x64 `
    -p:PublishSingleFile=false `
    --output $BridgeOutput
if ($LASTEXITCODE -ne 0) {
    throw "Pubblicazione del bridge EOS non riuscita (codice $LASTEXITCODE)."
}
Copy-Item -LiteralPath $EosSettings -Destination (Join-Path $BridgeOutput "eos.settings.json") -Force

$PackagedBridge = Join-Path $BridgeOutput "HolyWar.Multiplayer.Bridge.exe"
$PackagedEosDll = Join-Path $BridgeOutput "EOSSDK-Win64-Shipping.dll"
if (-not (Test-Path -LiteralPath $PackagedBridge) -or -not (Test-Path -LiteralPath $PackagedEosDll)) {
    throw "Il pacchetto multiplayer non contiene il bridge o la DLL EOS."
}
Write-Host "Verifica del bridge multiplayer incluso..."
& $PackagedBridge --self-test
if ($LASTEXITCODE -ne 0) {
    throw "Il bridge multiplayer incluso non ha superato il self-test."
}

Write-Host "Verifica dell'integrazione multiplayer nell'app pacchettizzata..."
$PackagedIndex = Join-Path $Root "dist\HolyWar\_internal\web_concept\index.html"
if (-not (Test-Path -LiteralPath $PackagedIndex) -or
    -not (Select-String -LiteralPath $PackagedIndex -SimpleMatch 'id="host-online-button"' -Quiet)) {
    throw "Il menu multiplayer non e presente nell'interfaccia pacchettizzata."
}
$MultiplayerProbe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$MultiplayerProbe.Start()
$MultiplayerSmokePort = ([System.Net.IPEndPoint]$MultiplayerProbe.LocalEndpoint).Port
$MultiplayerProbe.Stop()
$MultiplayerProcess = $null
try {
    $MultiplayerProcess = Start-Process `
        -FilePath $PackagedExe `
        -ArgumentList @("--no-browser", "--port", "$MultiplayerSmokePort") `
        -WorkingDirectory (Split-Path $PackagedExe) `
        -WindowStyle Hidden `
        -PassThru
    $MultiplayerHealthy = $false
    $MultiplayerLastError = "nessuna risposta"
    for ($Attempt = 0; $Attempt -lt 60; $Attempt++) {
        try {
            $Status = Invoke-RestMethod -Uri "http://127.0.0.1:$MultiplayerSmokePort/api/multiplayer/status" -TimeoutSec 1
            $Config = Invoke-RestMethod -Uri "http://127.0.0.1:$MultiplayerSmokePort/api/config" -TimeoutSec 1
            if ($Status.available -and $Config.application -eq "holywar") {
                $MultiplayerHealthy = $true
                break
            }
            $MultiplayerLastError = "endpoint avviato ma configurazione multiplayer non valida"
        }
        catch {
            $MultiplayerLastError = $_.Exception.Message
            Start-Sleep -Milliseconds 250
        }
    }
    if (-not $MultiplayerHealthy) {
        throw "L'app pacchettizzata non ha superato il test dell'interfaccia multiplayer: $MultiplayerLastError"
    }
}
finally {
    $MultiplayerListener = Get-NetTCPConnection -LocalPort $MultiplayerSmokePort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($MultiplayerListener) {
        $ActualMultiplayerProcess = Get-Process -Id $MultiplayerListener.OwningProcess -ErrorAction SilentlyContinue
        if ($ActualMultiplayerProcess -and $ActualMultiplayerProcess.Path -eq $PackagedExe) {
            Stop-Process -Id $ActualMultiplayerProcess.Id -Force
            $ActualMultiplayerProcess.WaitForExit()
        }
    }
    elseif ($MultiplayerProcess -and -not $MultiplayerProcess.HasExited) {
        Stop-Process -Id $MultiplayerProcess.Id -Force
        $MultiplayerProcess.WaitForExit()
    }
}

$WebViewBootstrapper = Join-Path $Root "installer\vendor\MicrosoftEdgeWebview2Setup.exe"
if (-not (Test-Path -LiteralPath $WebViewBootstrapper)) {
    Write-Host "Download del bootstrapper ufficiale Microsoft WebView2..."
    New-Item -ItemType Directory -Path (Split-Path $WebViewBootstrapper) -Force | Out-Null
    Invoke-WebRequest `
        -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" `
        -OutFile $WebViewBootstrapper `
        -UseBasicParsing
}
if ((Get-Item -LiteralPath $WebViewBootstrapper).Length -lt 1MB) {
    throw "Il bootstrapper WebView2 scaricato non e valido: $WebViewBootstrapper"
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
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup non e riuscito (codice $LASTEXITCODE)."
}

$InstallerPath = Join-Path $Root "installer\dist\HolyWar-Setup-$Version.exe"
if (-not (Test-Path -LiteralPath $InstallerPath)) {
    throw "Installer atteso non trovato: $InstallerPath"
}

Write-Host ""
Write-Host "Installer pronto: $InstallerPath" -ForegroundColor Green
