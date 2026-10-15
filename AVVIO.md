# Avviare Study Coach

Per la descrizione aggiornata dei flussi, del contatore di sessione e delle modifiche correnti, vedi [Study_Coach_Documentazione.pdf](Study_Coach_Documentazione.pdf).

## Requisiti

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/)
- Un file `.env` nella root con le chiavi dei provider AI selezionati (copia `.env.example`)

## Installazione

Dalla root del progetto:

```powershell
uv sync
```

Per eseguire anche i test:

```powershell
uv sync --extra dev
```

`uv sync` installa solo le dipendenze di esecuzione e può rimuovere `pytest` dall'ambiente: è normale. Usa `--extra dev` per installare ed eseguire i test.


## Avvio

Un solo terminale, dalla root:

```powershell
uv run uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8000
```

Apri **http://127.0.0.1:8000/** per l'interfaccia completa. La documentazione API è su **http://127.0.0.1:8000/docs**. L'URL `/` reindirizza alla pagina di accesso o agli esami, a seconda della sessione. Non occorrono `npm` né un secondo server.

## Test

```powershell
uv run --extra dev python -m pytest -q
uv lock --check
git diff --check
```

## Note operative

Il modello di embedding si carica al primo utilizzo. Il primo download può richiedere tempo. Le pagine PDF senza testo estraibile passano all'OCR locale. `MAX_UPLOAD_BYTES` limita la dimensione dei PDF. `CORS_ORIGINS` serve solo a eventuali client API su origini diverse: la UI inclusa è servita dallo stesso host di FastAPI.

I PDF con riferimenti interni difettosi possono essere letti da `pypdf` con recupero parziale: il server registra un solo riepilogo per file e mostra nell'interfaccia quante pagine hanno testo. Se mancano pagine, conviene esportare nuovamente il PDF dalla fonte originale. L'avviso Hugging Face sulle richieste senza `HF_TOKEN` riguarda i limiti del download del modello e non indica un errore di indicizzazione.

Per i quiz, il modello riceve un numero limitato di gruppi distribuiti tra le fonti e lungo il documento. Ogni citazione resta verificata letteralmente contro il testo indicizzato; una risposta priva di citazioni verificabili riceve un solo tentativo correttivo e poi viene scartata. Se nessun gruppo produce domande verificabili, l'interfaccia mostra un errore e la sessione non parte.

La creazione degli appunti mostra l'avanzamento sotto il pulsante, indicando fonte, parte e fase di verifica. A lavoro concluso compare **Scarica appunti PDF**. Se il provider restituisce un limite temporaneo, l'app mostra il tempo di attesa comunicato dal servizio; il PDF non viene pubblicato finché la verifica delle fonti non è completata.
