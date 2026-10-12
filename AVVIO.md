# Avviare Study Coach

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

## Modelli AI

Il file `.env.example` configura **tutor/sessioni su Groq**, **quiz su Mistral** e **appunti su Gemini**. Imposta `GROQ_API_KEY`, `MISTRAL_API_KEY` e `GEMINI_API_KEY` (oppure `GOOGLE_API_KEY`) nel tuo `.env`. Le chiavi restano sul server; il browser non le riceve.

`TUTOR_PROVIDER`, `QUIZ_PROVIDER` e `NOTES_PROVIDER` accettano `groq`, `mistral` o `gemini`. Le variabili `TUTOR_MODEL`, `QUIZ_MODEL` e `NOTES_MODEL` indicano l'ID del modello presso il relativo provider. Per tornare a una sola configurazione Groq, imposta tutti e tre i provider a `groq` e rimuovi le tre variabili `*_MODEL`: verrà usato `GROQ_MODEL`. Se ometti una variabile `*_MODEL`, viene usato il modello predefinito del relativo provider. Dopo aver modificato `.env`, riavvia il server.

Se Mistral restituisce HTTP 429 durante la generazione del quiz, `QUIZ_FALLBACK_PROVIDER=gemini` e `QUIZ_FALLBACK_MODEL=gemini-3-flash-preview` fanno proseguire con Gemini sulle stesse fonti selezionate. La citazione di ogni domanda resta verificata contro il testo indicizzato. Per disattivare il passaggio automatico, lascia vuoto `QUIZ_FALLBACK_PROVIDER`.
`RETRIEVAL_MAX_DISTANCE` vuoto non applica un limite di distanza. Se imposti un valore, deve essere un numero non negativo; scegli la soglia dopo aver valutato il retrieval sui tuoi materiali.

## Avvio

Un solo terminale, dalla root:

```powershell
uv run uvicorn backend.api.main:app --reload --host 127.0.0.1 --port 8000
```

Apri **http://127.0.0.1:8000/** per l'interfaccia completa. La documentazione API è su **http://127.0.0.1:8000/docs**. L'URL `/` reindirizza alla pagina di accesso o agli esami, a seconda della sessione. Non occorrono `npm` né un secondo server.

Il cookie HttpOnly `sc_token` gestisce l'accesso. **Esci** revoca la sessione. I turni di studio e la chat dei dubbi sono persistiti nel database.
I nuovi token di sessione sono cercati tramite digest SHA-256 indicizzato; i token bcrypt ancora attivi vengono convertiti al primo utilizzo. Il tutor accetta solo domande presenti nel quiz salvato e ricava dal database quelle ancora disponibili. La chiusura di una domanda salva la risposta e libera il turno nello stesso commit.
Nella pagina del tutor, **Nuova chat** crea una conversazione separata. **Tutte le chat** apre l'archivio per riaprire o eliminare una singola conversazione. Le chat esistenti ancora presenti nel database vengono raggruppate automaticamente al primo avvio con il nuovo schema.

## Test

```powershell
uv run --extra dev python -m pytest -q
uv lock --check
git diff --check
```

I test usano database e indice vettoriale isolati e non chiamano i provider AI. Le prove con un modello reale rimangono separate in `eval/`.

## Note operative

Il modello di embedding si carica al primo utilizzo. Il primo download può richiedere tempo. Le pagine PDF senza testo estraibile passano all'OCR locale. `MAX_UPLOAD_BYTES` limita la dimensione dei PDF. `CORS_ORIGINS` serve solo a eventuali client API su origini diverse: la UI inclusa è servita dallo stesso host di FastAPI.

I PDF con riferimenti interni difettosi possono essere letti da `pypdf` con recupero parziale: il server registra un solo riepilogo per file e mostra nell'interfaccia quante pagine hanno testo. Se mancano pagine, conviene esportare nuovamente il PDF dalla fonte originale. L'avviso Hugging Face sulle richieste senza `HF_TOKEN` riguarda i limiti del download del modello e non indica un errore di indicizzazione.

Per i quiz, il modello riceve un numero limitato di gruppi distribuiti tra le fonti e lungo il documento. Ogni citazione resta verificata letteralmente contro il testo indicizzato; una risposta priva di citazioni verificabili riceve un solo tentativo correttivo e poi viene scartata. Se nessun gruppo produce domande verificabili, l'interfaccia mostra un errore e la sessione non parte.

La creazione degli appunti mostra l'avanzamento sotto il pulsante, indicando fonte, parte e fase di verifica. A lavoro concluso compare **Scarica appunti PDF**. Se il provider restituisce un limite temporaneo, l'app mostra il tempo di attesa comunicato dal servizio; il PDF non viene pubblicato finché la verifica delle fonti non è completata.
