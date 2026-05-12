# AGENTS.md — Study Coach

## Overview

Assistente intelligente per la preparazione personalizzata agli esami universitari.
Lo studente carica materiale di studio (PDF, appunti) e il sistema gestisce sessioni
di interrogazione adattiva con metodo socratico, tracciamento progressi e report finale.
Supporta più studenti e più esami in sessioni separate e persistenti.

## Stack

- **Linguaggio:** Python 3.11+
- **Agent framework:** Agno (agenti, tool use, orchestrazione multi-agent)
- **LLM:** OpenAI GPT-4o via Agno (provider configurabile da `.env`)
- **Vector DB / RAG:** ChromaDB persistente (`data/chroma/`), embeddings OpenAI
- **UI:** Streamlit multi-pagina (`app/`)
- **API layer:** FastAPI + Uvicorn (`backend/api/`)
- **Persistenza:** SQLAlchemy + SQLite (`backend/db/`)
- **Modelli dati:** Pydantic v2 (`backend/models/`)
- **Ingestion PDF:** pypdf (`backend/agents/ingestor.py`)
- **Config e segreti:** python-dotenv (`.env`, mai committato)
- **Dipendenze:** `requirements.txt` + uv

## Struttura

```
study_coach/
├── app/                    # Frontend Streamlit
│   ├── pages/              # login, upload, session, history
│   └── main.py
├── backend/
│   ├── api/                # Router FastAPI
│   ├── agents/             # ingestor, quiz_generator, socratic_tutor, adaptive_engine
│   ├── models/             # Schemi Pydantic
│   └── db/                 # Modelli ORM + migrazioni
├── data/
│   ├── uploads/            # PDF temporanei
│   └── chroma/             # Indice vettoriale persistente
├── reports/                # Report sessioni esportati
├── tests/
├── .env
└── README.md
```

## Convenzioni

- **Naming:** snake_case per file, funzioni, variabili; PascalCase per classi Pydantic/SQLAlchemy
- **Agenti:** un agente per responsabilità — `ingestor`, `quiz_generator`, `socratic_tutor`,
  `adaptive_engine`; nessun agente monolitico
- **Prompt:** costanti o file dedicati nei moduli agente (`agents/`), mai inline in Streamlit o FastAPI
- **Isolamento dati:** ogni studente ha `student_id`; ogni esame ha `exam_id`; le collezioni
  ChromaDB usano namespace `{student_id}_{exam_id}`
- **Segreti:** tutte le API key e path in `.env`; accesso centralizzato tramite `config.py`
- **UI:** le pagine Streamlit contengono solo logica di presentazione; chiamano il backend via API

## Testing

- Framework: `pytest` (cartella `tests/`)
- Un file di test per modulo (`test_ingestor.py`, `test_rag.py`, `test_quiz_generator.py`, …)
- LLM e ChromaDB mockati nelle unit test; nessuna chiamata API reale in CI
- Priorità di coverage: pipeline RAG, logica di valutazione risposte, adaptive engine

## Evitare

- Chiavi API hardcoded nel codice o nei prompt
- Logica di business nelle pagine Streamlit (`app/pages/`)
- Un singolo agente che gestisce ingestion + quiz + valutazione + adattamento
- Accesso diretto a SQLite senza SQLAlchemy
- PDF permanenti in `data/uploads/` — pulire dopo l'indicizzazione
- Mischiare collezioni ChromaDB di studenti diversi (usare sempre namespace per `student_id`)
