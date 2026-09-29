# Avviare Study Coach

## 1. Requisiti
- Python >= 3.13
- Un file `.env` nella root del progetto con le API key necessarie:

```
GROQ_API_KEY=...
GROQ_MODEL=openai/gpt-oss-120b
GEMINI_API_KEY=...
MISTRAL_API_KEY=...
```

## 2. Installa le dipendenze

Con [uv](https://docs.astral.sh/uv/) (consigliato, il progetto usa `uv.lock`):

```bash
uv sync
```

In alternativa, con pip in un virtualenv attivo:

```bash
pip install -r requirements.txt  
```

## 3. Avvia l'app

```bash
streamlit run app/main.py
```

Poi apri il browser su [http://localhost:8501](http://localhost:8501).

Il tema è configurato in `.streamlit/config.toml`. Dopo un aggiornamento del
tema, riavvia Streamlit dalla root del progetto e ricarica la pagina per
applicare gli stessi colori anche ai widget nativi (slider, menu e upload).

L'accesso viene mantenuto tramite cookie anche dopo il refresh. Dopo questo
aggiornamento, accedi una volta per salvare il cookie con il nuovo meccanismo.
Il pulsante **Esci** revoca il token e cancella il cookie. Il ripristino riguarda
l'accesso e riapre la libreria degli esami; le risposte non ancora inviate
rimangono legate alla sessione Streamlit corrente.

Il logo vettoriale in `app/assets/logo.svg` viene usato nell'intestazione,
nella schermata di accesso e come favicon.

### Modificare lo stile

L'app include già il CSS compilato: per avviarla non serve Node.js.
Per modificare il design, aggiorna `app/styles/input.css` e i componenti
condivisi in `app/ui.py`, poi compila con:

```bash
npm ci
npm run build:css
```

Durante lo sviluppo puoi usare `npm run watch:css`. Tailwind usa il prefisso
`sc:` per le classi dei componenti HTML ed esclude Preflight per rispettare
i controlli Streamlit. Il risultato, `app/styles/app.css`, va incluso nel repository.
I colori dei widget in `.streamlit/config.toml` devono corrispondere ai token
in `app/styles/input.css`.

## 4. (Opzionale) Avvia anche l'API REST

L'app Streamlit funziona in autonomia (chiama direttamente il backend Python), ma se serve anche l'API FastAPI:

```bash
uvicorn backend.api.main:app --reload
```

Documentazione interattiva su [http://localhost:8000/docs](http://localhost:8000/docs).

## 5. Eseguire i test

```bash
pytest test/
```

Per verificare anche il componente browser del cookie (Node.js):

```bash
node --test test/session_cookie_client.test.mjs
```
