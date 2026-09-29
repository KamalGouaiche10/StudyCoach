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
