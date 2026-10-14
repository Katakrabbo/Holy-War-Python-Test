# Holy War

Holy War in Python con interfaccia web locale e motore a script carta-per-carta.

## Setup

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
```

## Avvio

Su Windows puoi fare doppio clic su `Avvia Holy War.bat`: al primo avvio crea automaticamente `.venv`, installa le dipendenze mancanti e apre l'interfaccia web.

In alternativa:

```powershell
.\.venv\Scripts\python.exe -m holywar.web --cards-json "holywar/data/cards.json"
```

Il comando apre `http://127.0.0.1:5174/` e mantiene tutte le regole nel motore Python.
Per non aprire automaticamente il browser aggiungi `--no-browser`.

Se vuoi usare deck premade custom, aggiungi `--premades-json "my_premades.json"` al comando.

I deck creati/modificati da GUI vengono salvati in:
- Windows: `%APPDATA%\HolyWar\premade_decks.json`

La vecchia GUI desktop e la CLI restano nel repository soltanto come riferimento compatibile durante il completamento del porting.

## Funzionalita MVP

- Modalita `1v1 locale` e `vs AI`
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

Prerequisiti:
- Inno Setup 6 installato (`ISCC.exe`)
- venv attiva con dipendenze (`pip install -e .[dev]`)

Comando completo (build exe + setup installer):

```powershell
.\scripts\build_installer.ps1 -Version 0.1.0
```

Comando rapido (se hai gia `dist\HolyWar` e vuoi solo rigenerare il setup):

```powershell
.\scripts\build_installer.ps1 -Version 0.1.0 -SkipPyInstaller
```

Cosa fa lo script:
- compila l'app web locale con PyInstaller in `dist\HolyWar\`
- include catalogo, script degli effetti, interfaccia web e deck precreati
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
