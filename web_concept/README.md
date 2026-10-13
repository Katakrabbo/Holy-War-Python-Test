# Holy War — web UI concept

Prototipo locale e completamente separato dal motore. Non importa né modifica `holywar/core`, `holywar/effects` o gli script delle carte.

## Avvio

Dalla cartella principale del progetto:

```powershell
.\.venv\Scripts\python.exe -m http.server 5173 --directory web_concept
```

Aprire quindi <http://127.0.0.1:5173>.

## Scopo

- verificare gerarchia visiva, leggibilità e disposizione del campo;
- rappresentare le tre colonne di Attacco/Difesa e l'avanzamento automatico nella stessa colonna;
- mantenere l'intera plancia visibile nel formato desktop standard 1920×1080;
- adattare automaticamente la dimensione dei nomi lunghi senza rimpicciolire tutte le carte;
- espandere la mano sopra il campo solo durante l'interazione dell'utente;
- affiancare Deck/Cimitero/Scomunicate e Supporti alle linee dei Santi per liberare altezza;
- mostrare una sola Ispirazione attiva con indicatore circolare;
- offrire un menu di pausa da tastiera tramite `ESC`;
- mantenere il log della partita sempre visibile nei 2/5 inferiori del pannello destro;
- provare drag-and-drop dalla mano, attacchi tramite trascinamento e targeting contestuale degli effetti;
- provare selezione carta, pannello dettaglio, bersagli validi e guida contestuale;
- raccogliere feedback prima di collegare il concept al motore Python.

Le interazioni sono simulate. Il collegamento al motore sarà una fase successiva e passerà attraverso un controller testabile, senza trasferire la logica degli effetti nel frontend.
