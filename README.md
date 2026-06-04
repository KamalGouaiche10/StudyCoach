# Study Coach 🎓

**Assistente intelligente per la preparazione personalizzata agli esami universitari.**

Study Coach è un sistema AI completo che supporta gli studenti nel percorso verso il successo accademico attraverso:
- Indicizzazione intelligente del materiale (RAG + ChromaDB)
- Generazione dinamica di quiz calibrati
- Interrogazione socratica adattiva con metodo Socrate
- Tracciamento dei progressi e report personalizzati

---

## 🚀 Caratteristiche Principali

### 📚 RAG (Retrieval-Augmented Generation)
- **Upload PDF**: Carica appunti e materiale di studio
- **Indicizzazione vettoriale**: ChromaDB persistente con embeddings locali (all-MiniLM-L6-v2)
- **Retrieval semantico**: Recupero intelligente dei contenuti rilevanti per ogni domanda

### 🎯 Quiz Generazione Adattiva
- **Quiz dinamici**: Generati dal materiale indicizzato usando Agno + Groq
- **Difficoltà progressiva**: base → intermedia → avanzata
- **Tema personalizzato**: Personalizzabile per topic specifici

### 🤔 Interrogazione Socratica
- **Loop adattivo per domanda**:
  1. Presentazione domanda
  2. Prima risposta → feedback socratico (guiding question)
  3. Seconda risposta → valutazione 0-10
  4. Contestazione opzionale → rivalutazione
- **Metodo Socrate**: Guida lo studente senza dare direttamente le risposte
- **Feedback costruttivo**: Punti corretti, lacune identificate, argomenti da rivedere

### 🧠 Adaptive Engine
- **Tracking topic**: Registra performance per singolo argomento
- **Prioritizzazione intelligente**: Propone prossime domande su aree deboli
- **Strategia adattiva**:
  1. Domande su topic deboli (media < 6 o primo tentativo scarso)
  2. Domande su topic non ancora visti
  3. Qualunque domanda rimanente

### 📊 Report Finale
- **Markdown + PDF**: Report completi e scaricabili
- **Performance per topic**: Tabelle dettagliate, grafici, metriche
- **Verdetto**: 🟢 Ottimo / 🟡 Sufficiente / 🔴 Insufficiente
- **Aree di miglioramento**: Consigli specifici su topic deboli

---

## 📋 Stack Tecnologico

| Componente | Tecnologie |
|---|---|
| **Linguaggio** | Python 3.11+ |
| **Framework Agent** | Agno (orchestrazione multi-agent) |
| **LLM** | Groq (llama-3.3-70b-versatile) via Agno |
| **Vector DB** | ChromaDB persistente (data/chroma/) |
| **Embeddings** | all-MiniLM-L6-v2 (locale, ~90MB) |
| **Frontend** | Streamlit multi-pagina |
| **Backend API** | FastAPI + Uvicorn |
| **Database** | SQLAlchemy + SQLite |
| **PDF** | pypdf per estrazione, fpdf2 per generazione |
| **Configurazione** | python-dotenv (.env) |

---

## 🛠️ Installazione

### Prerequisiti
- Python 3.11+
- pip o uv

### Setup Ambiente

```bash
# Clone repository
git clone <repo-url>
cd StudyCoach

# Installa dipendenze
pip install -r requirements.txt
# oppure
uv pip install -r requirements.txt

# Configura variabili d'ambiente
cp .env.example .env
# Edita .env con le tue API key (GROQ_API_KEY, etc.)
```

### Variabili d'Ambiente (.env)

```dotenv
GROQ_API_KEY=gsk_...          # API key Groq per LLM
GEMINI_API_KEY=AIzaSy...       # API key Google (facoltativo)
```

---

## 🚀 Avvio

### Frontend Streamlit
```bash
streamlit run app/main.py
```
Accedi a `http://localhost:8501`

### Backend API (FastAPI)
```bash
uvicorn backend.api.main:app --reload --port 8000
```
Accedi a:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Run Entrambi (parallelo)
```bash
# Terminal 1
streamlit run app/main.py

# Terminal 2
uvicorn backend.api.main:app --reload --port 8000
```

---

## 📖 Flusso Principale

```
LOGIN/REGISTER
    ↓
CARICA ESAME + PDF
    ↓
INDICIZZA MATERIALE (RAG)
    ↓
APRI SESSIONE STUDIO
    ↓
GENERA QUIZ
    ↓
LOOP SOCRATICO PER OGNI DOMANDA:
  1. Start → presenta domanda
  2. Answer 1 → feedback guida
  3. Answer 2 → valutazione 0-10
  4. Contest? (opzionale) → rivalutazione
  5. Close → salva tentativo
    ↓
ADAPTIVE ENGINE:
  - Traccia performance per topic
  - Sceglie prossima domanda su aree deboli
    ↓
RIPORTA ALL'UTENTE:
  - Media complessiva
  - Topic deboli/forti
  - Aree da rivedere
    ↓
GENERA REPORT:
  - Markdown (reports/{student}_{exam}_{session}.md)
  - PDF (reports/{student}_{exam}_{session}.pdf)
```

---

## 📁 Struttura Progetto

```
study_coach/
├── app/                           # Frontend Streamlit
│   ├── main.py                    # Entry point
│   └── pages/
│       ├── login.py               # Login/Register
│       ├── upload.py              # Gestione esami + PDF
│       ├── session.py             # Interrogazione socratica
│       └── history.py             # Storico sessioni
│
├── backend/
│   ├── api/                       # Router FastAPI
│   │   ├── main.py                # Entry point + CORS
│   │   ├── auth.py                # /auth/register, /auth/login
│   │   ├── exams.py               # /exams CRUD + upload PDF
│   │   └── sessions.py            # /sessions loop socratico + adaptive
│   │
│   ├── agents/                    # Multi-agent orchestration
│   │   ├── ingestor.py            # RAG: indicizzazione PDF
│   │   ├── quiz_generator.py      # Generazione domande (Agno)
│   │   ├── socratic_tutor.py      # Loop socratico (Agno)
│   │   ├── adaptive_engine.py     # Tracking + prioritizzazione
│   │   ├── report_generator.py    # Markdown + PDF
│   │   ├── notes_generator.py     # Appunti sintetici
│   │   ├── prompts/
│   │   │   ├── quiz_generator_v1.txt
│   │   │   ├── socratic_tutor_guide_v1.txt
│   │   │   ├── socratic_tutor_eval_v1.txt
│   │   │   └── socratic_tutor_contest_v1.txt
│   │   └── __init__.py
│   │
│   ├── db/
│   │   ├── models.py              # SQLAlchemy ORM (Student, Exam, Session)
│   │   └── __init__.py
│   │
│   ├── models/
│   │   ├── schemas.py             # Pydantic v2 per API
│   │   └── __init__.py
│   │
│   └── __init__.py
│
├── data/
│   ├── uploads/                   # PDF temporanei
│   ├── chroma/                    # ChromaDB persistente
│   └── study_coach.db             # SQLite
│
├── reports/                       # Report generati (MD + PDF)
├── tests/                         # Unit test
├── .env                           # API key (NOT COMMITTED)
├── .gitignore                     # Esclude .env, data/, __pycache__
├── requirements.txt               # Dipendenze Python
├── pyproject.toml                 # Configurazione Progetto
├── AGENTS.md                      # Documentazione architettura
└── README.md                      # Questo file
```

---

## 🔧 Configurazione

### Convezioni Progetto

- **Naming**: `snake_case` per file/funzioni; `PascalCase` per classi
- **Agenti**: Un agente per responsabilità (ingestor, quiz_generator, socratic_tutor, adaptive_engine)
- **Prompt**: File dedicati in `backend/agents/prompts/` versionati
- **Isolamento dati**: Ogni `(student_id, exam_id)` ha namespace separato in ChromaDB
- **Segreti**: Tutte in `.env`, mai hardcoded

### Parametri Chiave

| Parametro | Default | Descrizione |
|---|---|---|
| `DEFAULT_N_QUESTIONS` | 5 | Numero domande per quiz |
| `DEFAULT_N_CHUNKS` | 5-10 | Chunk RAG per retrieval |
| `CHUNK_SIZE` | 500 parole | Dimensione chunk testo |
| `CHUNK_OVERLAP` | 50 parole | Overlap tra chunk |
| `score_weak_threshold` | 6 | Topic è "debole" se media < 6 |

---

## ✅ Testing

```bash
# Unit test (mock LLM e ChromaDB)
pytest tests/ -v

# Coverage
pytest tests/ --cov=backend --cov-report=html

# Linting
flake8 backend/ app/ --max-line-length=120
black backend/ app/ --check

# Type checking
mypy backend/ app/ --ignore-missing-imports
```

---

## 📦 Deployment

### Docker (opzionale)
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["streamlit", "run", "app/main.py"]
```

### Produzione
```bash
# Install gunicorn
pip install gunicorn

# Run API backend
gunicorn backend.api.main:app -w 4 -b 0.0.0.0:8000

# Run Streamlit in modo produzione
streamlit run app/main.py --server.port 8501 --server.headless true
```

---

## 🐛 Troubleshooting

| Problema | Causa | Soluzione |
|---|---|---|
| `ModuleNotFoundError: agno` | Dipendenze non installate | `pip install -r requirements.txt` |
| `GROQ_API_KEY not found` | .env mancante | Crea `.env` con API key |
| `OperationalError: database is locked` | SQLite concorrente | Usa SQLite con journal mode WAL |
| `ChromaDB: no embedding function` | Embedding model non trovato | Scarica all-MiniLM-L6-v2 (primo run) |
| `Streamlit not found` | Python venv non attivato | Attiva venv: `. venv/Scripts/activate` (Windows) |

---

## 📚 Documentazione Aggiuntiva

- **Architettura**: Vedi [AGENTS.md](./AGENTS.md)
- **Dev Log**: Vedi [study_coach_devlog.md](./study_coach_devlog.md)
- **API Spec**: `http://localhost:8000/docs` (Swagger)

---

## 📞 Support

Per dubbi, bug o suggerimenti, apri una issue nel repository.

---

## 📄 Licenza

Progetto universitario. Uso libero per scopi didattici e di ricerca.

---

## ✨ Credits

Sviluppato con ❤️ per gli studenti di Programmazione AI — Università del Piemonte Orientale

**Stack**: Agno · Groq · ChromaDB · Streamlit · FastAPI · SQLAlchemy

