# 🎓 Study Coach — Documentazione Completa

> Assistente AI universitario per la preparazione personalizzata agli esami.
> Lo studente carica materiale (PDF) e il sistema gestisce sessioni di interrogazione
> adattiva con metodo socratico, tracciamento progressi e report finale.

---

## Indice

1. [Stack tecnologico](#1-stack-tecnologico)
2. [Struttura del progetto](#2-struttura-del-progetto)
3. [Architettura e pattern](#3-architettura-e-pattern)
4. [Flusso completo dall'avvio alla chiusura](#4-flusso-completo-dallAvvio-alla-chiusura)
5. [Frontend — `app/`](#5-frontend--app)
6. [Backend Agents — `backend/agents/`](#6-backend-agents--backendagents)
7. [Backend API — `backend/api/`](#7-backend-api--backendapi)
8. [Database ORM — `backend/db/`](#8-database-orm--backenddb)
9. [Schemi Pydantic — `backend/models/`](#9-schemi-pydantic--backendmodels)
10. [Configurazione e ambiente](#10-configurazione-e-ambiente)
11. [Come avviare il progetto](#11-come-avviare-il-progetto)

---

## 1. Stack tecnologico

| Livello | Tecnologia | Scopo |
|---|---|---|
| **LLM** | Groq (`llama-3.3-70b-versatile`) via Agno | Generazione domande, guida socratica, valutazione |
| **Agent framework** | [Agno](https://github.com/agno-ai/agno) | Creazione e gestione degli agenti LLM |
| **Embeddings** | `sentence-transformers` (`all-MiniLM-L6-v2`) | Vettorializzazione locale dei chunk PDF |
| **Vector DB** | ChromaDB persistente (`data/chroma/`) | Retrieval Augmented Generation (RAG) |
| **Frontend** | Streamlit multi-pagina (`app/`) | Interfaccia utente |
| **API** | FastAPI + Uvicorn (`backend/api/`) | Layer REST tra UI e backend |
| **ORM / DB** | SQLAlchemy + SQLite (`data/study_coach.db`) | Persistenza studenti, esami, sessioni |
| **Modelli dati** | Pydantic v2 (`backend/models/`) | Validazione request/response API |
| **PDF parsing** | pypdf (`backend/agents/ingestor.py`) | Estrazione testo dai PDF |
| **PDF generation** | fpdf2 | Generazione report PDF |
| **Config** | python-dotenv (`.env`) | Gestione API key e segreti |
| **Dependency mgmt** | uv + `requirements.txt` | Installazione dipendenze |

---

## 2. Struttura del progetto

```
StudyCoach/
├── app/                          # Frontend Streamlit
│   ├── main.py                   # Entry point, CSS globale, router pagine
│   └── pages/
│       ├── login.py              # Pagina login / registrazione
│       ├── upload.py             # Gestione esami e upload PDF
│       ├── session.py            # Sessione attiva (loop socratico)
│       └── history.py            # Storico sessioni e download report
│
├── backend/
│   ├── agents/                   # Agenti AI (logica di business)
│   │   ├── ingestor.py           # Indicizzazione PDF → ChromaDB
│   │   ├── quiz_generator.py     # Genera domande con RAG + LLM
│   │   ├── socratic_tutor.py     # Loop socratico (guida + valutazione)
│   │   ├── adaptive_engine.py    # Adattamento ordine domande sui topic deboli
│   │   ├── report_generator.py   # Genera report Markdown e PDF
│   │   ├── notes_generator.py    # Genera appunti sintetici
│   │   └── prompts/              # Prompt versionati in file .txt
│   │       ├── quiz_generator_v1.txt
│   │       ├── socratic_tutor_guide_v1.txt
│   │       ├── socratic_tutor_eval_v1.txt
│   │       ├── socratic_tutor_contest_v1.txt
│   │       └── notes_generator_v1.txt
│   │
│   ├── api/                      # Router FastAPI
│   │   ├── main.py               # App FastAPI, CORS, lifespan
│   │   ├── auth.py               # POST /auth/register, /login, /logout
│   │   ├── exams.py              # CRUD esami + upload PDF
│   │   └── sessions.py           # Flusso completo sessione socratica
│   │
│   ├── db/
│   │   └── models.py             # ORM SQLAlchemy: Student, Exam, Session
│   │
│   └── models/
│       └── schemas.py            # Schemi Pydantic request/response
│
├── data/
│   ├── uploads/                  # PDF temporanei (puliti dopo indicizzazione)
│   ├── chroma/                   # Indice vettoriale ChromaDB persistente
│   └── study_coach.db            # Database SQLite
│
├── reports/                      # Report sessioni (.md e .pdf)
├── tests/                        # Test pytest
├── .env                          # Variabili d'ambiente (non committato)
├── pyproject.toml
└── AGENTS.md                     # Convenzioni di sviluppo
```

---

## 3. Architettura e pattern

### Pattern principale: Layered Architecture + Agent-per-responsibility

```
┌─────────────────────────────────────────────────────┐
│                  FRONTEND (Streamlit)                │
│   login  →  upload  →  session  →  history          │
│   Solo logica di presentazione, chiama backend       │
└────────────────────────┬────────────────────────────┘
                         │  chiamate dirette Python
                         │  (no HTTP in modalità standalone)
┌────────────────────────▼────────────────────────────┐
│                  AGENTS LAYER                        │
│  ingestor  quiz_generator  socratic_tutor            │
│  adaptive_engine  report_generator  notes_generator  │
│  Ogni agente ha una sola responsabilità              │
└───────┬──────────────────────────┬──────────────────┘
        │                          │
┌───────▼──────────┐    ┌──────────▼──────────────────┐
│   ChromaDB RAG   │    │   SQLite (SQLAlchemy ORM)    │
│   data/chroma/   │    │   Student / Exam / Session   │
└──────────────────┘    └─────────────────────────────┘
```

### Pattern architetturali usati

| Pattern | Dove | Perché |
|---|---|---|
| **RAG** (Retrieval-Augmented Generation) | `ingestor.py` + tutti gli agenti | Ogni domanda/appunto è basato sul materiale reale del PDF |
| **Agent-per-responsibility** | Un file per agente in `agents/` | Isolamento, testabilità, sostituibilità del modello |
| **State Machine** | `TurnState` in `socratic_tutor.py` | Garantisce che il loop socratico rispetti l'ordine corretto |
| **Repository (semplificato)** | `SessionLocal` in ogni endpoint | Isola l'accesso al DB in helper functions |
| **Prompt versionati** | File `.txt` in `agents/prompts/` | Modificabili senza toccare il codice Python |
| **In-memory store** | `_active_tutors`, `_active_engines` in `sessions.py` | Stato effimero per sessione attiva (produzione: Redis) |
| **Namespace isolation** | Collection ChromaDB `student_{id}_exam_{id}` | Garantisce che gli studenti non vedano materiale altrui |
| **Graceful degradation** | `report_generator.py`, `save_report()` | Fallback su cartella temp se `reports/` non è scrivibile |

---

## 4. Flusso completo dall'avvio alla chiusura

```
1. LOGIN
   └─ Studente si registra o accede
      └─ `_hash_password()` → hash SHA-256
      └─ SQLite: Student row creata/verificata
      └─ `st.session_state.authenticated = True`

2. UPLOAD PDF
   └─ Studente crea un Exam (nome)
      └─ SQLite: Exam row creata
   └─ Studente carica un PDF
      └─ Salvato in `data/uploads/s{id}_e{id}_{nome}.pdf`
      └─ `ingest_pdf()`:
          ├─ pypdf estrae il testo pagina per pagina
          ├─ `chunk_text()` divide in chunk da 500 parole (overlap 50)
          ├─ `LocalEmbeddingFunction` vettorializza con all-MiniLM-L6-v2
          └─ Chunk salvati in ChromaDB collection `student_{id}_exam_{id}`

3. AVVIO SESSIONE
   └─ Streamlit crea DbSession nel DB
   └─ AdaptiveEngine inizializzato (sessione corrente)

4. GENERAZIONE QUIZ
   └─ `generate_quiz()`:
       ├─ `retrieve_chunks()` → ChromaDB RAG (top-8 chunk per topic query)
       ├─ Prompt versionato `quiz_generator_v1.txt` compilato con i chunk
       ├─ Agno Agent (Groq llama-3.3-70b) chiama l'LLM
       └─ JSON parsato → lista di Question(id, text, difficulty, topic_hint)

5. LOOP SOCRATICO (per ogni domanda)
   ├─ AdaptiveEngine.pick_next_question() sceglie la prossima domanda
   │    Priority: topic deboli → topic nuovi → qualsiasi
   │
   ├─ SocraticTutor.start(question)
   │    └─ Pre-fetch chunk RAG per la domanda specifica
   │
   ├─ [STATO: WAITING_ANSWER_1]
   │    └─ Studente scrive Prima Risposta
   │
   ├─ SocraticTutor.submit_answer_1(ans)
   │    └─ SocraticGuideAgent (Groq) genera:
   │         - guiding_question (NON dà la risposta)
   │         - positive_feedback
   │         - focus_area
   │
   ├─ [STATO: WAITING_ANSWER_2]
   │    └─ Studente legge la guida e scrive Seconda Risposta
   │
   ├─ SocraticTutor.submit_answer_2(ans)
   │    └─ EvaluatorAgent (Groq) valuta 0-10:
   │         - score, motivation
   │         - correct_points, missing_points
   │         - improvement_after_guidance
   │
   ├─ [STATO: EVALUATED]
   │    └─ (Opzionale) Studente contesta il voto
   │         └─ ContestationAgent (Groq) rivaluta:
   │              - final_score, score_changed, score_delta
   │              - contestation_assessment (valido/parzialmente_valido/non_valido)
   │              - response_to_student
   │
   ├─ [STATO: CONTESTED o EVALUATED]
   │    └─ _close_and_advance():
   │         ├─ tutor.close() → QuestionAttempt definitivo
   │         ├─ engine.record_answer(topic, score) → aggiorna TopicStats
   │         ├─ Tentativo serializzato in qa_log (JSON, colonna Text)
   │         └─ Se era l'ultima domanda → _save_session()
   │
   └─ Ripeti dal punto 5 per tutte le domande rimanenti

6. CHIUSURA SESSIONE
   └─ AdaptiveEngine.generate_session_report()
       ├─ Media generale, topic breakdown, weak/strong topics
       └─ Testo summary leggibile
   └─ save_report():
       ├─ generate_markdown() → reports/{sid}_{eid}_{sessid}.md
       └─ generate_pdf()     → reports/{sid}_{eid}_{sessid}.pdf
   └─ DbSession aggiornata: ended_at, score_total, report_path

7. STORICO
   └─ history.py mostra tutte le sessioni con score e durata
   └─ Download PDF report
   └─ Generazione appunti post-sessione (notes_generator)
```

---

## 5. Frontend — `app/`

### `app/main.py` — Entry point Streamlit

Avviato con `streamlit run app/main.py`.

**Responsabilità:**
- Configura la pagina Streamlit (titolo, icona, layout wide).
- Inietta il **CSS globale** (font Syne + Inter da Google Fonts, design system dark con variabili CSS, badge, card, colori score).
- Inizializza `st.session_state` con i valori default.
- Implementa il **router** a singola pagina: legge `st.session_state.current_page` e importa dinamicamente la funzione `render()` della pagina corrente.

**`st.session_state` — chiavi principali:**

| Chiave | Tipo | Significato |
|---|---|---|
| `authenticated` | `bool` | L'utente è loggato |
| `student_id` | `int \| None` | ID dello studente corrente |
| `username` | `str \| None` | Username visualizzato |
| `current_page` | `str` | Pagina attiva: `"login"`, `"upload"`, `"session"`, `"history"` |
| `current_exam` | `dict \| None` | `{"id": int, "name": str}` |
| `current_session` | `dict \| None` | `{"id": int, "questions": [...], "remaining": [...], "attempts": [...], "scores": [...]}` |
| `quiz_result` | `QuizResult \| None` | Risultato quiz generato |
| `adaptive_engine` | `AdaptiveEngine \| None` | Engine adattivo della sessione corrente |
| `tutor` | `SocraticTutor \| None` | Tutor socratico per la domanda corrente |
| `tutor_state` | `str` | Stato macchina: `"idle"`, `"answer1"`, `"answer2"`, `"evaluated"`, `"contested"` |
| `current_q_idx` | `int` | Indice domanda corrente |

---

### `app/pages/login.py`

Pagina di login e registrazione. **Non usa HTTP**: chiama direttamente `SessionLocal` di SQLAlchemy.

#### `_hash_password(pwd: str) -> str`
Restituisce l'hash SHA-256 della password. Usato sia in registrazione che in verifica login.

- `pwd` — password in chiaro da hashare.

#### `_login(username: Optional[str], password: Optional[str]) -> tuple[bool, str]`
Verifica le credenziali nel DB. Aggiorna `st.session_state` in caso di successo.

- `username` — username inserito dall'utente (può essere `None` per i type stub di Streamlit).
- `password` — password in chiaro.
- **Ritorna** `(True, "ok")` se login riuscito, `(False, messaggio_errore)` altrimenti.

#### `_register(username, password, confirm) -> tuple[bool, str]`
Crea un nuovo account studente nel DB.

- `username` — username scelto (min 3 caratteri, unico).
- `password` — password scelta (min 6 caratteri).
- `confirm` — conferma password (deve corrispondere a `password`).
- **Ritorna** `(True, "ok")` se registrazione riuscita.

#### `render() -> None`
Entry point chiamata dal router. Mostra il layout con due tab (Login / Registrazione) in colonna centrata. Se già autenticato, redirige a `"upload"`.

---

### `app/pages/upload.py`

Gestione esami: creazione, upload PDF, indicizzazione, avvio sessione, generazione appunti.

#### `_require_auth() -> None`
Guard: se non autenticato, redirige a `"login"` e fa `st.rerun()`.

#### `_get_exams(student_id: int) -> list`
Recupera tutti gli esami dello studente dal DB, ordinati per data di creazione (più recente prima).

- `student_id` — ID dello studente.

#### `_create_exam(student_id: int, name: str) -> Exam`
Crea un nuovo esame vuoto nel DB.

- `student_id` — ID dello studente proprietario.
- `name` — nome dell'esame (trimmed).

#### `_delete_exam(exam_id: int, student_id: int) -> None`
Elimina l'esame dal DB (cascade su sessioni) e la relativa collection ChromaDB.

- `exam_id` — ID esame da eliminare.
- `student_id` — ID studente (per verifica ownership).

#### `_session_count(exam_id: int) -> int`
Ritorna il numero di sessioni associate all'esame.

#### `_avg_score(exam_id: int) -> float | None`
Calcola la media dei `score_total` di tutte le sessioni completate dell'esame.

#### `_close_orphan_sessions(exam_id: int) -> int`
Prima di avviare una nuova sessione, chiude tutte le sessioni senza `ended_at` (orfane per disconnessione browser). Imposta `ended_at = now`. Ritorna il numero di sessioni chiuse.

- `exam_id` — esame per cui cercare sessioni orfane.

#### `_navbar() -> None`
Renderizza la navbar con: logo Study Coach, bottone "Storico", bottone "Esci" (pulisce `session_state`).

#### `_render_notes_panel(exam: Exam, student_id: int) -> None`
Genera e mostra (inline, con cache in `session_state`) gli appunti sintetici dal RAG dell'esame, usando `generate_notes()`. Offre il download come file `.md`.

- `exam` — oggetto ORM Exam.
- `student_id` — ID studente per il RAG.

#### `render() -> None`
Entry point. Mostra la dashboard con la lista degli esami. Per ogni esame visualizza card con statistiche e bottoni: upload PDF, avvia sessione, genera appunti, storico, elimina.

---

### `app/pages/session.py`

Gestisce la sessione di studio attiva: generazione quiz + loop socratico + chiusura.

#### `_require_auth() -> None` / `_require_exam() -> None`
Guard di navigazione: se mancano autenticazione o esame selezionato, redirigono alla pagina corretta.

#### `_attempt_to_log_entry(attempt: QuestionAttempt, final_score: int) -> dict`
Converte un oggetto `QuestionAttempt` (dataclass) nel formato piatto (dict) usato da `history.py` e salvato nel `qa_log` del DB.

- `attempt` — tentativo chiuso dal `SocraticTutor`.
- `final_score` — voto finale (post eventuale contestazione).

#### `_navbar() -> None`
Mostra: breadcrumb "Study Coach › Nome Esame", bottone "← Esci". Alla pressione del tasto Esci, se la sessione è parzialmente completata chiama `_mark_session_interrupted()`.

#### `_mark_session_interrupted(sess: dict) -> None`
Marca nel DB una sessione interrotta prematuramente: imposta `ended_at = now` e salva il `qa_log` parziale (domande già risposte). Non genera report né imposta `score_total`.

- `sess` — dict `current_session` da `st.session_state`.

#### `_progress_bar(current: int, total: int, scores: list) -> None`
Renderizza barra di avanzamento, contatore domande, media score corrente.

- `current` — domande completate.
- `total` — totale domande della sessione.
- `scores` — lista voti accumulati.

#### `_score_badge(score: int) -> str`
Ritorna HTML con il badge colorato per un voto (🟢 ≥8, 🟡 ≥6, 🔴 <6).

#### `_diff_badge(diff: str) -> str`
Ritorna HTML con il badge difficoltà ("base", "intermedia", "avanzata").

#### `_create_db_session(exam_id: int) -> int`
Crea una nuova riga `Session` nel DB e ritorna il suo ID.

- `exam_id` — esame per cui creare la sessione.

#### `_save_session(session_id, attempts, engine, exam) -> Optional[str]`
Salva la sessione completata nel DB e genera i report (MD + PDF). Controlla che la sessione non sia già stata salvata (guard `ended_at is not None`) per evitare doppi salvataggi causati da `st.rerun()`.

- `session_id` — ID della sessione nel DB.
- `attempts` — lista di dict log entries.
- `engine` — `AdaptiveEngine` con le statistiche della sessione.
- `exam` — dict `{"id": int, "name": str}`.
- **Ritorna** il path del PDF generato, o `None` in caso di errore.

#### `_render_quiz_generation() -> None`
Fase 1. Mostra lo slider per scegliere il numero di domande (3-10) e il bottone "Genera domande". Alla pressione: chiama `generate_quiz()`, crea `AdaptiveEngine`, crea `DbSession`, popola `current_session` in `session_state`.

#### `_render_active_session() -> None`
Fase 2. Orchestratore della macchina a stati per la domanda corrente:
- **idle**: `engine.pick_next_question()` + `SocraticTutor.start()` + `st.rerun()`
- **answer1**: text area + bottone → `tutor.submit_answer_1()`
- **answer2**: mostra guida socratica + text area → `tutor.submit_answer_2()`
- **evaluated**: mostra voto, punti corretti/mancanti, expander contestazione
- **contested**: mostra risultato contestazione

#### `_close_and_advance(engine, current_q, final_score, sess) -> None`
Chiude la domanda corrente e avanza alla prossima:
1. `tutor.close()` → QuestionAttempt definitivo
2. `engine.record_answer(question_id, topic, score)`
3. Serializza il tentativo nel log
4. Rimuove la domanda da `remaining`
5. Se non ci sono più domande rimaste → `_save_session()`
6. Reset stato tutor → `st.rerun()`

- `engine` — AdaptiveEngine della sessione.
- `current_q` — dict della domanda appena chiusa.
- `final_score` — voto finale (dopo eventuale contestazione).
- `sess` — dict `current_session`.

#### `_render_session_complete() -> None`
Fase 3. Mostra il riepilogo finale: media, emoji/label per livello, lista domande con voti, bottone download PDF, bottone "Vai allo storico", bottone "Nuova sessione".

#### `render() -> None`
Entry point. Chiama i guard, la navbar, poi instrada verso la fase corretta in base allo stato di `current_session` e `tutor_state`.

---

### `app/pages/history.py`

Storico sessioni: visualizza tutte le sessioni di un esame con Q&A, report PDF, appunti.

#### `_rebuild_report_payload(sess: DbSession) -> Optional[dict]`
Ricostruisce un payload report minimale partendo dal `qa_log` serializzato della sessione, per poter rigenerare il PDF se il file è andato perso.

- `sess` — oggetto ORM Session.
- **Ritorna** dict compatibile con `generate_pdf()` / `generate_markdown()`, o `None` se i dati sono insufficienti.

#### `_regenerate_pdf_report(session_id: int, exam_name: str) -> bool`
Rigenera e salva su disco il PDF di una sessione già completata che ha perso il file.

- `session_id` — ID sessione.
- `exam_name` — nome esame (per il titolo del PDF).
- **Ritorna** `True` se PDF salvato con successo.

#### `_require_auth() -> None`
Guard di autenticazione.

#### `_get_all_exams(student_id: int) -> list`
Recupera tutti gli esami dello studente ordinati per data (più recente prima).

#### `_get_sessions(exam_id: int) -> list`
Recupera tutte le sessioni di un esame, ordinate per data di inizio decrescente.

#### `_delete_session(session_id: int) -> None`
Elimina una sessione dal DB.

#### `_close_session(session_id: int) -> None`
Chiude manualmente una sessione orfana (ended_at NULL) impostando `ended_at = now`. Usato dal bottone "Segna conclusa".

#### `_is_orphan(sess: DbSession) -> bool`
Ritorna `True` se la sessione è orfana (non è mai stata chiusa correttamente: `ended_at is None`).

#### `_format_duration(started_at, ended_at) -> str`
Calcola e formatta la durata di una sessione come `"Xm Ys"`. Gestisce datetime naive e aware (bug comune con SQLite).

#### `_score_color(score: float) -> str`
Ritorna il codice colore CSS per un voto (`#10b981` verde ≥8, `#f59e0b` giallo ≥6, `#f43f5e` rosso <6).

#### `_verdict_emoji(score: float) -> str`
Ritorna l'emoji per il livello del voto (🟢🟡🔴).

#### `_navbar() -> None`
Navbar con logo e bottone "← Esami".

#### `_is_valid_attempt(attempt: dict) -> bool`
Controlla che un dict del `qa_log` abbia il campo minimo `"question_text"` (per gestire formati legacy).

#### `_render_session_detail(sess: DbSession) -> None`
Renderizza il dettaglio Q&A di una sessione all'interno di un expander. Per ogni tentativo mostra: domanda, badge difficoltà, voto, topic, prima risposta, guida socratica, seconda risposta, motivazione voto, risultato contestazione (se presente).

#### `_render_notes_panel(sess: DbSession) -> None`
Genera e mostra gli appunti sintetici post-sessione (con cache in `session_state`) usando `generate_notes_from_log()`.

#### `_go_to_session(exam) -> None`
Resetta lo stato di sessione e redirige a `"session"` per l'esame scelto.

#### `render() -> None`
Entry point. Mostra selectbox esame, statistiche aggregate (sessioni totali, completate, media, miglior voto), lista sessioni con card, bottoni per: dettaglio Q&A, appunti, download PDF, chiusura orfana, eliminazione.

---

## 6. Backend Agents — `backend/agents/`

### `backend/agents/ingestor.py`

Gestisce indicizzazione PDF → ChromaDB e il retrieval RAG.

#### Classe `LocalEmbeddingFunction`

Sottoclasse di `chromadb.EmbeddingFunction`. Usa `sentence-transformers` (`all-MiniLM-L6-v2`, ~90MB, 384 dimensioni) per produrre embeddings localmente senza API key.

**Metodo `__call__(self, texts: Documents) -> Embeddings`**
- `texts` — lista di stringhe da vettorializzare.
- **Ritorna** lista di vettori float (shape `[n, 384]`).

---

#### `get_collection(student_id: int, exam_id: int) -> chromadb.Collection`
Crea o recupera la collection ChromaDB per lo specifico studente+esame. Il nome segue il pattern `student_{student_id}_exam_{exam_id}` per l'isolamento dei namespace.

- `student_id` — ID studente.
- `exam_id` — ID esame.

---

#### `chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]`
Divide un testo in chunk di parole con overlap per continuità semantica.

- `text` — testo da dividere.
- `chunk_size` — numero massimo di parole per chunk (default 500).
- `overlap` — parole condivise tra chunk consecutivi (default 50).
- **Ritorna** lista di stringhe-chunk.

---

#### `ingest_pdf(pdf_path: str, student_id: int, exam_id: int) -> dict`
Pipeline completa di indicizzazione di un PDF:
1. Legge tutte le pagine con `pypdf.PdfReader`.
2. Salta le pagine senza testo estraibile (PDF scansionati).
3. Per ogni pagina chiama `chunk_text()`.
4. Scarta chunk < 20 caratteri.
5. Costruisce liste parallel di documenti, metadati e ID univoci (`s{sid}_e{eid}_c{counter}`).
6. Carica in ChromaDB a batch da 100 (per evitare limiti di memoria).
7. Ritorna dict con statistiche: `{file, pages, chunks, collection}`.

- `pdf_path` — path assoluto al PDF.
- `student_id` — ID studente (namespace ChromaDB).
- `exam_id` — ID esame (namespace ChromaDB).

---

#### `retrieve_chunks(query: str, student_id: int, exam_id: int, n_results: int = 5) -> list[str]`
Esegue una query semantica su ChromaDB per recuperare i chunk più rilevanti.

- `query` — testo della query (es. testo della domanda).
- `student_id` — per selezionare la collection corretta.
- `exam_id` — per selezionare la collection corretta.
- `n_results` — numero di chunk da restituire (default 5).
- **Ritorna** lista di stringhe-chunk, o lista vuota se nessun risultato.

---

#### `delete_exam_collection(student_id: int, exam_id: int) -> None`
Elimina la collection ChromaDB dell'esame (usato quando si elimina un esame). Ignora silenziosamente `ValueError` se la collection non esiste.

---

### `backend/agents/quiz_generator.py`

Genera N domande a risposta aperta basate sul materiale RAG.

#### Dataclass `Question`
Rappresenta una singola domanda del quiz.

| Campo | Tipo | Descrizione |
|---|---|---|
| `id` | `int` | Identificativo progressivo |
| `text` | `str` | Testo della domanda |
| `difficulty` | `str` | `"base"`, `"intermedia"`, `"avanzata"` |
| `topic_hint` | `str` | Argomento principale (usato dall'AdaptiveEngine) |

#### Dataclass `QuizResult`
Contenitore del risultato di una sessione di generazione quiz.

| Campo | Tipo | Descrizione |
|---|---|---|
| `questions` | `list[Question]` | Lista domande generate |
| `source_name` | `str` | Nome della fonte (es. nome del PDF) |
| `n_questions` | `int` | Numero effettivo di domande |
| `prompt_version` | `str` | Versione del prompt usato |
| `exam_id` | `int` | ID esame |
| `student_id` | `int` | ID studente |

---

#### `_load_prompt_template() -> str`
Carica il file `prompts/quiz_generator_v1.txt` e ritorna solo il corpo del prompt (dopo il separatore `---\n\n`).

#### `_parse_llm_response(raw: str) -> dict`
Pulisce la risposta grezza dell'LLM (rimuove markdown code fence ` ```json `) e fa `json.loads`. Solleva `ValueError` se il JSON non è valido o manca il campo `questions`.

- `raw` — stringa grezza restituita dall'LLM.

#### `_make_quiz_agent(model_name: str) -> Agent`
Factory che crea un `Agent` Agno con modello Groq. Il description del agente definisce il ruolo di "docente universitario" che risponde SOLO con JSON valido.

- `model_name` — ID modello Groq (es. `"llama-3.3-70b-versatile"`).

---

#### `generate_quiz(student_id, exam_id, topic_query, n_questions, n_chunks, source_name, model_name) -> QuizResult`
Funzione principale del modulo. Flusso in 5 step:
1. RAG retrieval da ChromaDB (`retrieve_chunks`).
2. Carica il prompt versionato.
3. Compila il prompt con `n_questions`, `source_name`, `context_chunks`.
4. Chiama l'Agno Agent (Groq).
5. Parsa il JSON e costruisce il `QuizResult`.

| Parametro | Default | Descrizione |
|---|---|---|
| `student_id` | — | ID studente |
| `exam_id` | — | ID esame |
| `topic_query` | `"concetti principali del corso"` | Query RAG per selezionare i chunk |
| `n_questions` | `5` | Numero di domande da generare |
| `n_chunks` | `8` | Chunk RAG da fornire al modello |
| `source_name` | `"materiale di studio"` | Nome visualizzato nella domanda |
| `model_name` | `"llama-3.3-70b-versatile"` | Modello Groq |

#### `quiz_to_dict(result: QuizResult) -> dict`
Serializza il `QuizResult` in un dict Python (usa `dataclasses.asdict`).

#### `quiz_to_json(result: QuizResult, indent: int = 2) -> str`
Serializza il `QuizResult` in una stringa JSON.

---

### `backend/agents/socratic_tutor.py`

Gestisce il loop socratico a macchina di stati per una singola domanda. Usa **3 agent Agno distinti**, uno per ogni step.

#### Enum `TurnState`
Macchina a stati del loop socratico:

| Stato | Significato |
|---|---|
| `WAITING_ANSWER_1` | In attesa della prima risposta dello studente |
| `WAITING_ANSWER_2` | Prima risposta ricevuta, domanda guida inviata, attende seconda risposta |
| `EVALUATED` | Seconda risposta valutata, voto emesso |
| `CONTESTED` | Voto contestato e rivalutato |
| `CLOSED` | Loop chiuso, tentativo definitivo |

#### Dataclass `EvaluationResult`
Risultato della valutazione dell'EvaluatorAgent.

| Campo | Tipo | Descrizione |
|---|---|---|
| `score` | `int` | Voto 0-10 |
| `motivation` | `str` | Spiegazione del voto |
| `correct_points` | `list[str]` | Concetti corretti citati |
| `missing_points` | `list[str]` | Concetti mancanti |
| `improvement_after_guidance` | `str` | Commento sul miglioramento dopo la guida |

#### Dataclass `ContestationResult`
Risultato della rivalutazione del ContestationAgent.

| Campo | Tipo | Descrizione |
|---|---|---|
| `final_score` | `int` | Voto finale rivalutato |
| `score_changed` | `bool` | Se il voto è cambiato |
| `score_delta` | `int` | Differenza rispetto al voto originale |
| `contestation_assessment` | `str` | `"valido"`, `"parzialmente_valido"`, `"non_valido"` |
| `final_motivation` | `str` | Motivazione del voto finale |
| `response_to_student` | `str` | Risposta narrativa allo studente |

#### Dataclass `QuestionAttempt`
Contenitore completo di un tentativo su una domanda. Accumulato durante il loop.

| Campo | Tipo | Descrizione |
|---|---|---|
| `question_id` | `int` | ID domanda |
| `question_text` | `str` | Testo domanda |
| `difficulty` | `str` | Difficoltà |
| `topic_hint` | `str` | Argomento |
| `student_answer_1` | `str` | Prima risposta studente |
| `guiding_question` | `str` | Domanda guida del tutor |
| `positive_feedback` | `str` | Feedback positivo del tutor |
| `focus_area` | `str` | Area su cui concentrarsi |
| `student_answer_2` | `str` | Seconda risposta studente |
| `evaluation` | `EvaluationResult \| None` | Valutazione |
| `contestation_text` | `str` | Testo contestazione studente |
| `contestation_result` | `ContestationResult \| None` | Risultato contestazione |
| `state` | `TurnState` | Stato corrente |

**Proprietà `final_score -> int | None`**: ritorna il voto finale (da contestazione se disponibile, altrimenti da valutazione).

---

#### Helpers interni

##### `_load_prompt(version_name: str) -> str`
Carica un file prompt da `agents/prompts/{version_name}.txt` e ritorna il corpo dopo `---\n\n`.

##### `_parse_json(raw: str) -> dict`
Pulisce e parsa la risposta JSON dell'LLM. Solleva `ValueError` se non valido.

##### `_guide_agent(model_name: str) -> Agent`
Factory per il **SocraticGuideAgent**: istruito a NON dare mai la risposta, a guidare con domande mirate.

##### `_eval_agent(model_name: str) -> Agent`
Factory per l'**EvaluatorAgent**: valuta la preparazione 0-10 con obiettività.

##### `_contest_agent(model_name: str) -> Agent`
Factory per il **ContestationAgent**: riesamina con imparzialità dopo la contestazione.

---

#### Step LLM interni

##### `_generate_guiding_question(attempt, context_chunks, model_name) -> dict`
Chiama il SocraticGuideAgent con prompt `socratic_tutor_guide_v1.txt` compilato con: domanda, prima risposta studente, chunk RAG. Ritorna dict con `guiding_question`, `positive_feedback`, `focus_area`.

##### `_evaluate(attempt, context_chunks, model_name) -> EvaluationResult`
Chiama l'EvaluatorAgent con prompt `socratic_tutor_eval_v1.txt` compilato con: domanda, risposta1, domanda guida, risposta2, chunk RAG. Ritorna `EvaluationResult` con score clampato 0-10.

##### `_re_evaluate_after_contestation(attempt, context_chunks, model_name) -> ContestationResult`
Chiama il ContestationAgent con prompt `socratic_tutor_contest_v1.txt` compilato con: tutto il dialogo + contestazione dello studente + voto originale. Calcola il delta score.

---

#### Classe `SocraticTutor`

Gestisce il loop socratico per **una singola domanda**.

##### `__init__(self, student_id, exam_id, model_name, n_chunks)`
| Parametro | Default | Descrizione |
|---|---|---|
| `student_id` | — | Per il RAG (namespace ChromaDB) |
| `exam_id` | — | Per il RAG |
| `model_name` | `"llama-3.3-70b-versatile"` | Modello Groq |
| `n_chunks` | `5` | Chunk RAG da pre-fetchare |

Attributi interni: `attempt: QuestionAttempt | None`, `_context_cache: list[str]` (chunk pre-fetchati).

##### `start(self, question_data: dict) -> str`
Inizializza un nuovo `QuestionAttempt` e pre-fetcha i chunk RAG per la domanda.

- `question_data` — dict con `id`, `text`, `difficulty`, `topic_hint`.
- **Ritorna** il testo della domanda.

##### `submit_answer_1(self, answer: str) -> dict`
Registra la prima risposta e chiama `_generate_guiding_question()`. Transizione a `WAITING_ANSWER_2`.

- `answer` — testo risposta dello studente.
- **Ritorna** `{"guiding_question", "positive_feedback", "focus_area"}`.

##### `submit_answer_2(self, answer: str) -> dict`
Registra la seconda risposta e chiama `_evaluate()`. Transizione a `EVALUATED`.

- `answer` — testo seconda risposta.
- **Ritorna** `{"score", "motivation", "correct_points", "missing_points", "improvement_after_guidance", "can_contest": True}`.

##### `submit_contestation(self, argumentation: str) -> dict`
Registra la contestazione e chiama `_re_evaluate_after_contestation()`. Transizione a `CONTESTED`.

- `argumentation` — argomentazione dello studente (min 10 caratteri via schema Pydantic).
- **Ritorna** `{"final_score", "score_changed", "score_delta", "contestation_assessment", "final_motivation", "response_to_student"}`.

##### `close(self) -> QuestionAttempt`
Chiude il loop. Valida che lo stato sia `EVALUATED` o `CONTESTED`. Transizione a `CLOSED`. Ritorna il `QuestionAttempt` definitivo.

##### `to_dict(self) -> dict` / `to_json(self) -> str`
Serializzazione del tentativo corrente (per il `qa_log` nel DB).

##### `_assert_state(self, expected: TurnState) -> None`
Guard interno: solleva `RuntimeError` se lo stato corrente non corrisponde all'atteso.

---

### `backend/agents/adaptive_engine.py`

Analizza i risultati progressivi della sessione e adatta l'ordine delle domande. **Nessuna chiamata LLM** — logica Python pura.

#### Dataclass `TopicStats`
Statistiche per un singolo argomento nella sessione corrente.

| Campo | Tipo | Descrizione |
|---|---|---|
| `topic` | `str` | Nome dell'argomento |
| `scores` | `list[int]` | Lista voti ottenuti su questo topic |

**Proprietà:**
- `avg_score -> float`: media dei voti (0.0 se vuoto).
- `n_attempts -> int`: numero di domande risposte.
- `is_weak -> bool`: `True` se media < 6, o singolo tentativo con voto < 5.

#### Dataclass `SessionStats`
Statistiche aggregate dell'intera sessione.

| Campo | Tipo | Descrizione |
|---|---|---|
| `student_id` | `int` | ID studente |
| `exam_id` | `int` | ID esame |
| `topic_stats` | `dict[str, TopicStats]` | Statistiche per topic |
| `answered_question_ids` | `list[int]` | ID domande già risposte |

**Proprietà:**
- `overall_avg -> float`: media su tutti i voti della sessione.
- `weak_topics -> list[str]`: topic con `is_weak == True`.
- `strong_topics -> list[str]`: topic con `is_weak == False`.

---

#### Classe `AdaptiveEngine`

##### `__init__(self, student_id: int, exam_id: int)`
Crea una `SessionStats` vuota per la sessione corrente.

##### `record_answer(self, question_id: int, topic: str, score: int) -> None`
Registra il risultato di una domanda completata. Da chiamare dopo ogni `tutor.close()`.

- `question_id` — ID domanda appena risposta.
- `topic` — `topic_hint` dalla domanda (es. `"Attention mechanism"`).
- `score` — voto finale 0-10 (clampato difensivamente).

##### `pick_next_question(self, remaining: list[dict]) -> dict | None`
Sceglie la prossima domanda con tre livelli di priorità:
1. **Domande su topic deboli** (media < 6).
2. **Domande su topic non ancora visti** nella sessione.
3. **Prima domanda rimanente** qualsiasi.

- `remaining` — lista di dict Question con `id` e `topic_hint`.
- **Ritorna** il dict della domanda scelta, o `None` se lista vuota.

##### `generate_session_report(self) -> dict`
Genera il report finale della sessione: media generale, breakdown per topic ordinato per score crescente, lista topic deboli e forti, testo summary.

**Ritorna** dict serializzabile con campi:
`student_id`, `exam_id`, `overall_avg`, `n_questions_answered`, `weak_topics`, `strong_topics`, `topic_breakdown`, `summary`.

##### `to_json(self) -> str`
Serializza `SessionStats` in JSON (per salvataggio intermedio).

---

#### `_build_summary(stats: SessionStats) -> str`
Funzione interna che costruisce il testo di riepilogo leggibile del report:
- ≥ 8: "Ottima prestazione complessiva."
- ≥ 6: "Prestazione sufficiente con margini di miglioramento."
- < 6: "Prestazione insufficiente: è necessario rivedere il materiale."
- Aggiunge lista topic deboli e padroneggiati.

---

### `backend/agents/report_generator.py`

Genera il report finale della sessione in formato Markdown e PDF.

#### `_pdf_safe_text(value: object) -> str`
Converte un testo in latin-1 (encoding richiesto da FPDF core fonts), sostituendo caratteri non supportati con `?` e rimpiazzando `—` con `-`.

---

#### `generate_markdown(report: dict, session_id: int, exam_name: str) -> str`
Genera il report in formato Markdown strutturato con tabelle, sezioni e emoji.

- `report` — dict prodotto da `AdaptiveEngine.generate_session_report()`.
- `session_id` — ID sessione (per l'intestazione).
- `exam_name` — nome esame (default `"Esame"`).
- **Ritorna** stringa Markdown.

---

#### Classe `_ReportPDF` (sottoclasse FPDF)
Personalizza header (logo "Study Coach - Report Sessione" + linea separatrice) e footer (numero pagina centrato).

#### `_add_section_title(pdf: FPDF, title: str) -> None`
Aggiunge un titolo di sezione con font Helvetica Bold 13pt, colore scuro, linea separatrice.

#### `_add_body(pdf: FPDF, text: str) -> None`
Aggiunge un paragrafo di testo con font Helvetica 11pt.

---

#### `generate_pdf(report: dict, session_id: int, exam_name: str) -> bytes`
Genera il report PDF completo:
1. Titolo + data generazione.
2. Sezione "Risultato Complessivo" con score colorato (verde/giallo/rosso).
3. Tabella "Performance per Argomento" per ogni topic.
4. Sezione "Aree da Rivedere" (topic deboli).
5. Sezione "Punti di Forza" (topic forti).
6. Sezione "Sintesi".

**Ritorna** i byte del PDF.

---

#### `save_report(report: dict, session_id: int, exam_name: str) -> dict[str, str]`
Coordina la generazione e il salvataggio su disco di MD e PDF. Gestisce errori con try/except indipendenti per MD e PDF (un errore nel PDF non blocca il salvataggio del MD). Fallback su cartella temp se `reports/` non è scrivibile.

- **Ritorna** `{"md": path_md, "pdf": path_pdf}` (stringa vuota se fallito).

---

### `backend/agents/notes_generator.py`

Genera appunti sintetici in due modalità: da materiale RAG (pre-sessione) o da `qa_log` (post-sessione).

#### `_load_prompt_template() -> str`
Carica `prompts/notes_generator_v1.txt`.

#### `_make_notes_agent(model_name: str) -> Agent`
Factory per il **NotesGeneratorAgent**: istruito a creare appunti strutturati con titoli, elenchi puntati, grassetto. Risponde in Markdown (`markdown=True`).

#### `_build_log_summary(attempts: list[dict]) -> str`
Estrae dal `qa_log` un testo formattato con domanda, topic, voto, risposta dello studente e lacune rilevate, per contestualizzare la generazione degli appunti.

- `attempts` — lista di dict dal `qa_log`.

#### `_extract_weak_topics(attempts: list[dict]) -> list[str]`
Raccoglie i topic con `final_score < 6` dal `qa_log`, deduplicati mantenendo l'ordine di prima occorrenza.

---

#### `generate_notes(student_id, exam_id, topic_query, n_chunks, source_name, model_name) -> str`
Genera appunti dal materiale RAG indicizzato (pre-sessione). Usa `retrieve_chunks()` + prompt `notes_generator_v1.txt` con `mode="materiale"`.

| Parametro | Default | Descrizione |
|---|---|---|
| `student_id` | — | Per il RAG |
| `exam_id` | — | Per il RAG |
| `topic_query` | `"concetti principali del corso"` | Query RAG |
| `n_chunks` | `10` | Chunk da recuperare |
| `source_name` | `"materiale di studio"` | Nome sorgente negli appunti |
| `model_name` | `"llama-3.3-70b-versatile"` | Modello Groq |

**Ritorna** stringa Markdown con gli appunti.

---

#### `generate_notes_from_log(attempts, student_id, exam_id, source_name, model_name, enrich_with_rag) -> str`
Genera appunti post-sessione focalizzati sulle lacune emerse durante l'interrogazione.

| Parametro | Default | Descrizione |
|---|---|---|
| `attempts` | — | Lista dict dal `qa_log` |
| `student_id` | `None` | Opzionale: per enrichment RAG |
| `exam_id` | `None` | Opzionale: per enrichment RAG |
| `source_name` | `"sessione di studio"` | Nome sorgente |
| `model_name` | `"llama-3.3-70b-versatile"` | Modello Groq |
| `enrich_with_rag` | `False` | Se True aggiunge chunk RAG sui topic deboli |

**Ritorna** stringa Markdown con gli appunti personalizzati sulle lacune.

---

## 7. Backend API — `backend/api/`

L'API FastAPI è il layer REST opzionale (il frontend Streamlit può chiamare direttamente il backend Python). Utile per deployment separato o testing via Swagger.

### `backend/api/main.py`

#### `lifespan(_app: FastAPI)`
Context manager async. All'avvio chiama `init_db()` per creare le tabelle SQLite se non esistono.

#### App FastAPI
- **CORS**: permette richieste da `localhost:8501` (Streamlit) e `127.0.0.1:8501`.
- **Router inclusi**: `auth_router` (`/auth`), `exams_router` (`/exams`), `sessions_router` (`/sessions`).

#### `health() -> dict`
`GET /health` — Health check. Ritorna `{"status": "ok", "service": "Study Coach API"}`.

---

### `backend/api/auth.py` — Router `/auth`

#### `_hash_password(pwd: str) -> str`
SHA-256 della password.

#### `_get_student_by_username(username: str) -> Student | None`
Query DB per username. Apre e chiude la sessione SQLAlchemy.

#### `register(payload: RegisterRequest) -> AuthResponse`
`POST /auth/register` — Crea un nuovo studente. Solleva 409 se username già in uso, 500 per errori DB.

#### `login(payload: LoginRequest) -> AuthResponse`
`POST /auth/login` — Verifica credenziali. Ritorna 401 per utente non trovato o password errata. Non emette JWT (autenticazione stateless via `session_state` Streamlit).

#### `logout() -> dict`
`POST /auth/logout` — Placeholder stateless. Il logout avviene lato client.

---

### `backend/api/exams.py` — Router `/exams`

#### `_get_exam_or_404(exam_id: int, student_id: int) -> Exam`
Helper che recupera l'esame verificando che appartenga allo studente. Solleva 404 se non trovato.

#### `_enrich_exam(exam: Exam, db) -> ExamResponse`
Aggiunge a `ExamResponse` il conteggio sessioni e la media score (da tutte le sessioni completate dell'esame).

#### `list_exams(student_id: int) -> ExamListResponse`
`GET /exams?student_id={id}` — Lista esami con statistiche aggregate, ordinati per data creazione.

#### `create_exam(payload: ExamCreate, student_id: int) -> ExamResponse`
`POST /exams?student_id={id}` — Crea un esame vuoto. Il PDF si carica separatamente via `/ingest`.

#### `delete_exam(exam_id: int, student_id: int) -> None`
`DELETE /exams/{exam_id}?student_id={id}` — Elimina esame dal DB (cascade su sessioni) + collection ChromaDB.

#### `ingest_pdf_endpoint(exam_id, student_id, file) -> IngestResponse`
`POST /exams/{exam_id}/ingest?student_id={id}` — Riceve il file PDF (`UploadFile`), lo salva in `data/uploads/`, chiama `ingest_pdf()`. Ritorna statistiche indicizzazione.

- `file` — file PDF caricato (validato con `.lower().endswith(".pdf")`).

---

### `backend/api/sessions.py` — Router `/sessions`

**In-memory store:**
- `_active_tutors: dict[str, SocraticTutor]` — chiave `"{session_id}_{question_id}"`.
- `_active_engines: dict[int, AdaptiveEngine]` — chiave `session_id`.

#### `_get_session_or_404(session_id: int) -> DbSession`
Recupera la sessione DB o solleva 404.

#### `_session_to_response(sess: DbSession) -> SessionResponse`
Converte ORM Session in Pydantic SessionResponse.

#### `create_session(payload, student_id) -> SessionResponse`
`POST /sessions?student_id={id}` — Crea DbSession nel DB e inizializza `AdaptiveEngine` in memoria.

#### `generate_session_quiz(session_id, payload, student_id) -> QuizGenerateResponse`
`POST /sessions/{id}/quiz` — Chiama `generate_quiz()` e ritorna la lista di domande.

#### `tutor_start(session_id, payload, student_id) -> TutorStartResponse`
`POST /sessions/{id}/tutor/start` — Crea `SocraticTutor`, chiama `tutor.start()`, salva in `_active_tutors`.

#### `tutor_answer1(session_id, payload) -> Answer1Response`
`POST /sessions/{id}/tutor/answer1` — Chiama `tutor.submit_answer_1()`. Gestisce 404 (tutor non trovato) e 409 (stato errato).

#### `tutor_answer2(session_id, payload) -> Answer2Response`
`POST /sessions/{id}/tutor/answer2` — Chiama `tutor.submit_answer_2()`.

#### `tutor_contest(session_id, payload) -> ContestResponse`
`POST /sessions/{id}/tutor/contest` — Chiama `tutor.submit_contestation()`.

#### `tutor_close(session_id, payload) -> CloseQuestionResponse`
`POST /sessions/{id}/tutor/close` — Chiude il loop socratico, aggiorna `AdaptiveEngine`, persiste il tentativo nel `qa_log`, rimuove il tutor dall'in-memory store.

#### `_append_attempt_to_log(session_id: int, attempt_dict: dict) -> None`
Aggiunge il tentativo serializzato al `qa_log` JSON della sessione nel DB (append-only).

#### `next_question(session_id, payload) -> NextQuestionResponse`
`POST /sessions/{id}/next-question` — Chiama `engine.pick_next_question()` sulla lista domande rimanenti.

#### `close_session(session_id, payload) -> SessionReportResponse`
`POST /sessions/{id}/close` — Genera report, salva MD+PDF, aggiorna DbSession (`ended_at`, `score_total`, `report_path`), rimuove engine dall'in-memory store.

#### `get_session(session_id) -> SessionResponse`
`GET /sessions/{id}` — Dettaglio sessione.

#### `list_sessions(exam_id) -> SessionListResponse`
`GET /sessions?exam_id={id}` — Lista sessioni per esame, ordinate per data decrescente.

---

## 8. Database ORM — `backend/db/models.py`

Il database è SQLite, acceduto tramite SQLAlchemy ORM. Il path è assoluto (relativo a `models.py`) per evitare errori di working directory.

### Classe `Student`
Tabella `students`.

| Colonna | Tipo | Vincoli | Descrizione |
|---|---|---|---|
| `id` | Integer | PK | ID univoco studente |
| `username` | String(50) | UNIQUE, NOT NULL | Username di accesso |
| `password_hash` | String(128) | NOT NULL | Hash SHA-256 della password |
| `created_at` | DateTime | default=now_utc | Timestamp creazione |
| `exams` | relationship | cascade delete | Esami associati |

### Classe `Exam`
Tabella `exams`.

| Colonna | Tipo | Vincoli | Descrizione |
|---|---|---|---|
| `id` | Integer | PK | ID univoco esame |
| `student_id` | Integer | FK(students.id), NOT NULL | Studente proprietario |
| `name` | String(100) | NOT NULL | Nome dell'esame |
| `created_at` | DateTime | default=now_utc | Timestamp creazione |
| `student` | relationship | | Studente associato |
| `sessions` | relationship | cascade delete | Sessioni associate |

### Classe `Session`
Tabella `sessions`.

| Colonna | Tipo | Vincoli | Descrizione |
|---|---|---|---|
| `id` | Integer | PK | ID univoco sessione |
| `exam_id` | Integer | FK(exams.id), NOT NULL | Esame associato |
| `started_at` | DateTime | default=now_utc | Inizio sessione |
| `ended_at` | DateTime | nullable | Fine sessione (NULL se orfana) |
| `score_total` | Float | nullable | Media voti sessione |
| `qa_log` | Text | nullable | JSON list dei tentativi |
| `report_path` | String(200) | nullable | Path assoluto al PDF report |
| `exam` | relationship | | Esame associato |

### `now_utc() -> datetime`
Funzione usata come `default` per i campi `DateTime`. Ritorna `datetime.now(timezone.utc)`.

### `init_db() -> None`
Crea tutte le tabelle se non esistono (`Base.metadata.create_all(engine)`).

### `SessionLocal`
`sessionmaker` configurato sul `engine` SQLite. Usato come factory per aprire sessioni DB nei vari moduli.

---

## 9. Schemi Pydantic — `backend/models/schemas.py`

Tutti gli schemi usano Pydantic v2. Separazione netta tra Request (dati in entrata) e Response (dati restituiti).

### Auth
| Schema | Tipo | Campi principali |
|---|---|---|
| `RegisterRequest` | Request | `username` (3-50 char), `password` (min 6) |
| `LoginRequest` | Request | `username`, `password` |
| `AuthResponse` | Response | `student_id`, `username`, `message` |

### Exams
| Schema | Tipo | Campi principali |
|---|---|---|
| `ExamCreate` | Request | `name` (1-100 char) |
| `ExamResponse` | Response | `id`, `student_id`, `name`, `created_at`, `n_sessions`, `avg_score` |
| `ExamListResponse` | Response | `exams: list[ExamResponse]`, `total` |
| `IngestResponse` | Response | `file`, `pages`, `chunks`, `collection`, `message` |

### Quiz
| Schema | Tipo | Campi principali |
|---|---|---|
| `QuizGenerateRequest` | Request | `topic_query`, `n_questions` (1-20), `source_name` |
| `QuestionOut` | DTO | `id`, `text`, `difficulty`, `topic_hint` |
| `QuizGenerateResponse` | Response | `exam_id`, `student_id`, `questions: list[QuestionOut]`, ... |

### Sessions
| Schema | Tipo | Campi principali |
|---|---|---|
| `SessionCreate` | Request | `exam_id` |
| `SessionResponse` | Response | `id`, `exam_id`, `started_at`, `ended_at`, `score_total`, `report_path` |
| `SessionListResponse` | Response | `sessions: list[SessionResponse]`, `total` |

### Socratic Tutor loop
| Schema | Tipo | Campi principali |
|---|---|---|
| `TutorStartRequest` | Request | `session_id`, `question: QuestionOut` |
| `TutorStartResponse` | Response | `question_text`, `difficulty`, `topic_hint` |
| `Answer1Request` | Request | `session_id`, `question_id`, `answer` (min 1) |
| `Answer1Response` | Response | `guiding_question`, `positive_feedback`, `focus_area` |
| `Answer2Request` | Request | `session_id`, `question_id`, `answer` |
| `Answer2Response` | Response | `score` (0-10), `motivation`, `correct_points`, `missing_points`, `improvement_after_guidance`, `can_contest` |
| `ContestRequest` | Request | `session_id`, `question_id`, `argumentation` (min 10) |
| `ContestResponse` | Response | `final_score`, `score_changed`, `score_delta`, `contestation_assessment`, `final_motivation`, `response_to_student` |
| `CloseQuestionRequest` | Request | `session_id`, `question_id` |
| `CloseQuestionResponse` | Response | `final_score`, `topic_hint` |

### Adaptive Engine & Report
| Schema | Tipo | Campi principali |
|---|---|---|
| `NextQuestionRequest` | Request | `session_id`, `remaining_questions: list[QuestionOut]` |
| `NextQuestionResponse` | Response | `question: QuestionOut \| None`, `is_last`, `message` |
| `SessionCloseRequest` | Request | `session_id`, `exam_name` |
| `TopicBreakdown` | DTO | `topic`, `avg_score`, `n_attempts`, `is_weak` |
| `SessionReportResponse` | Response | `overall_avg`, `weak_topics`, `strong_topics`, `topic_breakdown`, `summary`, `report_md_path`, `report_pdf_path` |

---

## 10. Configurazione e ambiente

### File `.env` (non committato)

```env
GROQ_API_KEY=gsk_...           # API key Groq per gli agenti LLM
```

### Variabili usate
- **`GROQ_API_KEY`**: letta automaticamente da Agno tramite `dotenv` per autenticare le chiamate al modello `llama-3.3-70b-versatile`.
- Gli embeddings usano `sentence-transformers` **localmente** (no API key necessaria). Il modello `all-MiniLM-L6-v2` viene scaricato automaticamente la prima volta (~90MB).

---

## 11. Come avviare il progetto

### Prerequisiti
- Python 3.11+
- `uv` o `pip`

### Installazione

```bash
# Clona il repository
git clone <repo-url>
cd StudyCoach

# Crea virtual environment e installa dipendenze
uv venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

uv pip install -r requirements.txt
```

### Configura l'ambiente

Crea il file `.env` nella root del progetto:

```env
GROQ_API_KEY=gsk_la_tua_chiave_groq
```

### Avvia il frontend Streamlit (modalità standalone)

```bash
streamlit run app/main.py
```

Apri `http://localhost:8501` nel browser.

### (Opzionale) Avvia il backend FastAPI

```bash
uvicorn backend.api.main:app --reload --port 8000
```

Docs API disponibili su:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Esegui i test

```bash
pytest tests/
```

---

## Note architetturali importanti

> **Modalità operative**: Il frontend Streamlit può funzionare in due modalità:
> 1. **Standalone** (default): chiama direttamente il codice Python del backend (agent, db, ecc.) senza passare per HTTP. È la modalità usata in sviluppo.
> 2. **API-first**: il frontend chiama FastAPI via HTTP. Utile per deployment separato o per test via Swagger.

> **In-memory store**: `_active_tutors` e `_active_engines` in `sessions.py` vivono nella RAM del processo FastAPI. In caso di riavvio del server, le sessioni attive vengono perse. Per produzione multi-processo: sostituire con Redis + TTL.

> **ChromaDB namespace isolation**: ogni coppia `(student_id, exam_id)` ha la propria collection ChromaDB (`student_{sid}_exam_{eid}`). Questo garantisce che gli studenti non vedano mai il materiale altrui e che l'eliminazione di un esame pulisca correttamente tutti i vettori associati.

> **Prompt versionati**: tutti i prompt sono file `.txt` separati dal codice, con un header di metadati separato da `---\n\n`. Per modificare il comportamento di un agente basta editare il file `.txt` senza toccare Python.
