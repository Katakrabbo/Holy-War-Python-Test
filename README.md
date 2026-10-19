# Holy War

Holy War in Python con interfaccia web locale e motore a script carta-per-carta.

## Setup

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
```

## Avvio

Se hai Node.js installato, dalla cartella del progetto puoi avviare l'app come una normale app web:

```powershell
npm run dev
```

Al primo avvio il comando crea automaticamente `.venv`, installa le dipendenze Python mancanti e apre `http://127.0.0.1:5174/`. Arresta il server con `Ctrl+C`. Non serve eseguire `npm install`, perche il progetto non ha dipendenze Node.

Su Windows puoi fare doppio clic su `Avvia Holy War.bat`: al primo avvio crea automaticamente `.venv`, installa le dipendenze mancanti e apre l'interfaccia web.

In alternativa:

```powershell
.\.venv\Scripts\python.exe -m holywar.web --cards-json "holywar/data/cards.json"
```

Il comando apre Holy War in una finestra desktop dedicata e mantiene tutte le regole nel motore Python.
Per la diagnostica puoi ancora aprire l'interfaccia nel browser con `--browser`, oppure avviare
soltanto il servizio locale con `--no-browser`.

Gli stessi parametri funzionano anche con il comando npm:

```powershell
npm run dev -- --browser
```

Prima di aggiungere o modificare carte puoi controllare dati e script senza avviare una partita:

```powershell
.\.venv\Scripts\python.exe -m holywar.validation
```

Il comando non modifica alcun file: termina con codice `1` se trova errori strutturali e distingue gli avvisi non bloccanti.

Se vuoi usare deck premade custom, aggiungi `--premades-json "my_premades.json"` al comando.

I deck creati/modificati da GUI vengono salvati in:
- Windows: `%APPDATA%\HolyWar\premade_decks.json`

La vecchia GUI desktop e la CLI restano nel repository soltanto come riferimento compatibile durante il completamento del porting.

## Funzionalita MVP

- Modalita `1v1 locale`, `vs AI` e multiplayer online 1v1 tramite Epic Online Services
- Deck test deterministici per ogni religione (niente deck casuali)
- Deck premade selezionabili per religione nella GUI
- Meccaniche core: pesca, ispirazione, mano max 8, campo attacco/difesa, attacchi, peccato, cimitero, scomunica, token
- Effetti implementati carta per carta tramite script
- Deck Editor e Laboratorio Partita integrati
- Log partita consultabile nell'interfaccia
- Test automatici con `pytest`

## Architettura Effetti

- `holywar/effects/library.py`: dispatcher leggero
- `holywar/effects/runtime.py`: facade runtime con dataclass/spec comuni
- `holywar/effects/runtime_sections/registry.py`: bootstrap script e proprieta statiche carta
- `holywar/effects/runtime_sections/resolution.py`: play/enter/activate e binding trigger
- `holywar/effects/runtime_sections/effects.py`: dispatcher centrale delle action runtime
- `holywar/effects/runtime_sections/effects_combat.py`: buff/debuff, scudi, equipment, damage, faith/strength combat effects
- `holywar/effects/runtime_sections/effects_board.py`: stato turno/campo, swap righe, controllo temporaneo, sigilli e tick speciali
- `holywar/effects/runtime_sections/effects_decking.py`: draw, mill, recover, ricerca e manipolazione reliquiario/cimitero
- `holywar/effects/runtime_sections/effects_removal.py`: destroy, excommunicate e spostamenti semplici verso la mano/uscita campo
- `holywar/effects/runtime_sections/effects_resources.py`: sin, inspiration e faith/flag effects
- `holywar/effects/runtime_sections/effects_summoning.py`: summon, token e ingressi sul campo
- `holywar/effects/runtime_sections/effects_targeting.py`: targeting, move tra zone, equipment, token summon
- `holywar/effects/runtime_sections/effects_conditions.py`: matching eventi/condizioni e requirement cards
- `holywar/effects/card_scripts/cards/...`: script per carta, uno per file

## Note

Il motore usa nomi/variabili in inglese e testi output in italiano.

## Installer Windows (.exe setup)

Prerequisiti sul solo PC usato per creare l'installer:
- Python 3.11 o successivo
- Inno Setup 6 installato (`ISCC.exe`)
- SDK EOS C# estratto e credenziali configurate come descritto in `multiplayer/README.md`
- SDK .NET 8 (installabile localmente con `scripts\setup_multiplayer_dev.ps1`)

Gli amici che installano il gioco non devono avere Python, Node.js, .NET o Inno Setup.

Comando completo (build exe + setup installer):

```powershell
.\scripts\build_installer.ps1 -Version 0.2.0
```

Il comando crea automaticamente `.venv` se manca, installa gli strumenti di build,
esegue i test, genera l'app portabile e verifica che il suo server locale risponda
prima di compilare l'installer.

Comando rapido (se hai gia `dist\HolyWar` e vuoi solo rigenerare il setup):

```powershell
.\scripts\build_installer.ps1 -Version 0.2.0 -SkipPyInstaller
```

Cosa fa lo script:
- compila l'app web locale con PyInstaller in `dist\HolyWar\`
- include catalogo, script degli effetti, interfaccia web e deck precreati
- pubblica il bridge EOS e il runtime .NET 8 self-contained in `dist\HolyWar\multiplayer\`
- verifica il bridge incluso prima di creare il setup
- compila l'installer Inno Setup usando `installer\HolyWar.iss`

Output finale:
- `installer\dist\HolyWar-Setup-<version>.exe`

L'installer crea:
- installazione per utente in `%LOCALAPPDATA%\Programs\Holy War` (non richiede privilegi amministrativi)
- shortcut menu Start
- shortcut desktop (opzionale)
- disinstallazione standard Windows

La disinstallazione rimuove anche:
- `%APPDATA%\HolyWar`
- `%LOCALAPPDATA%\HolyWar`
- `%LOCALAPPDATA%\Temp\HolyWar`

Se l'app installata non parte:
- controlla il log `%APPDATA%\HolyWar\startup_error.log`
