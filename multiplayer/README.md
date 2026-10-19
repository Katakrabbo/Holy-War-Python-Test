# Holy War Multiplayer

Il multiplayer usa un host autorevole: il motore Python dell'host valida i comandi e invia a ogni giocatore una vista privata dello stato. Il bridge C# isola il trasporto dal motore.

## Stato attuale

- protocollo bridge JSON Lines versione 1;
- provider simulato per verificare lifecycle, lobby e pacchetti;
- supporto `online` nel motore web con identita giocatore esplicita;
- snapshot separati per host e ospite;
- provider EOS reale con login Device ID, lobby a due giocatori e trasporto P2P affidabile;
- menu desktop `Ospita partita` / `Entra in partita` con codice lobby;
- host autorevole e sincronizzazione delle azioni, delle scelte e delle opzioni bersaglio;
- frammentazione degli snapshot sopra il limite dei singoli pacchetti EOS;
- bridge e runtime .NET inclusi nell'installer Windows;
- provider simulato ancora disponibile per i test offline.

## Prova fra due PC

Installa lo stesso `HolyWar-Setup-<version>.exe` su entrambi i computer. Sul primo scegli
`Multiplayer online`, quindi `Crea lobby` e copia il codice. Sul secondo seleziona la stessa
modalita, incolla il codice e premi `Entra nella lobby`. La partita parte quando l'host riceve
il profilo dell'ospite. Non servono port forwarding o un server locale raggiungibile dall'altro PC.

Per simulare reti differenti puoi attivare una VPN su uno solo dei due PC; EOS usera il relay
quando il collegamento diretto non e disponibile.

## Verifica locale

```powershell
.\scripts\setup_multiplayer_dev.ps1
.\scripts\test_multiplayer_bridge.ps1
```

## Materiale EOS richiesto

1. Creare il prodotto Holy War nel Developer Portal.
2. Creare Sandbox e Deployment di sviluppo.
3. Creare una Client Policy custom, con `User required` e la feature Lobbies abilitata.
4. Scaricare l'SDK EOS C# per Windows dal Developer Portal.
5. Estrarre l'SDK in `multiplayer/eos-sdk/` (cartella ignorata da Git).
6. Eseguire `scripts/configure_eos.ps1` e inserire le credenziali richieste (file ignorato da Git).

Avvio manuale del provider EOS:

```powershell
.\.tools\dotnet\dotnet.exe run --project .\multiplayer\HolyWar.Multiplayer.Bridge -c Release -- --provider eos
```

Il bridge gestisce solo autenticazione, lobby e trasporto: le regole restano nel motore Python autorevole.
