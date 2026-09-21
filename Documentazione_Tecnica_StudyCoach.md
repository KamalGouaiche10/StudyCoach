# Study Coach — Documentazione Tecnica

> Guida di riferimento: come funziona la catena end-to-end del progetto, e a cosa serve ogni classe/funzione, file per file.

---

## 1. La catena del progetto (come funziona, passo per passo)

```
┌─────────────┐      ┌──────────────────┐      ┌───────────────────┐
│  Upload PDF │ ───▶ │  ingestor.py     │ ───▶ │  ChromaDB          │
│  (exam.py / │      │  chunk + embed   │      │  (per studente+es.)│
│  upload.py) │      └──────────────────┘      └───────────────────┘
└─────────────┘                                          │
                                                          ▼
┌──────────────────────┐   RAG (retrieve_chunks)   ┌─────────────────────┐
│  quiz_generator.py    │ ◀────────────────────────┤  retrieve_chunks()  │
│  genera N domande     │                           └─────────────────────┘
└──────────┬────────────┘
           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  LOOP SOCRATICO (per ogni domanda)                   │
│  socratic_tutor.py                                                   │
│  1) submit_answer_1()  → Guide Agent  → domanda guida                │
│  2) submit_answer_2()  → Eval Agent   → punteggio + motivazione      │
│  3) submit_contestation() (opz.) → Contest Agent → voto finale       │
│  4) close()            → QuestionAttempt definitivo                  │
└──────────┬────────────────────────────────────────────────────────────┘
           ▼
┌─────────────────────────┐
│  adaptive_engine.py     │  record_answer() aggiorna le statistiche per topic
│  pick_next_question()   │  sceglie la prossima domanda (priorità ai topic deboli)
└──────────┬───────────────┘
           │  (si ripete finché non finiscono le domande)
           ▼
┌─────────────────────────┐      ┌───────────────────────────┐
│ report_generator.py     │      │ notes_generator.py         │
│ genera report MD + PDF  │      │ genera appunti MD/PDF       │
│ (da adaptive_engine)    │      │ (da materiale o da qa_log)  │
└──────────┬───────────────┘      └──────────┬─────────────────┘
           ▼                                 ▼
┌─────────────────────────────────────────────────────────────┐
│  backend/db/models.py  (SQLite via SQLAlchemy)               │
│  Student → Exam → Material / Session (qa_log, score, report) │
└─────────────────────────────────────────────────────────────┘
```

**In sintesi, cosa succede quando uno studente usa l'app:**

1. **Login/Registrazione** (`login.py` + `models.Student`): l'utente si autentica; un cookie persistente (`session_cookie.py`) permette il login automatico ai refresh successivi.
2. **Gestione esami** (`upload.py`): l'utente crea un "esame" (es. "Analisi 1"), che è solo un contenitore logico.
3. **Upload materiale** (`exam.py` → `ingestor.ingest_pdf`): i PDF caricati vengono spezzati in chunk di testo, trasformati in embeddings locali (sentence-transformers) e salvati in una collection ChromaDB dedicata a quello studente+esame.
4. **Avvio sessione** (`session.py` → `quiz_generator.generate_quiz`): il sistema recupera i chunk più rilevanti (RAG) e chiede a un LLM (Llama 3.3 70B via Groq) di generare N domande a risposta aperta in formato JSON.
5. **Loop socratico** (`socratic_tutor.SocraticTutor`), per ogni domanda:
   - lo studente risponde una prima volta;
   - il **Guide Agent** genera una domanda guida (mai la soluzione) per stimolare la riflessione;
   - lo studente risponde una seconda volta;
   - l'**Eval Agent** assegna un punteggio 0-10 con motivazione, punti corretti/mancanti;
   - lo studente può **contestare** il voto: un **Contest Agent** terzo rivaluta in modo imparziale;
   - la domanda viene chiusa (`close()`) e il risultato passa all'`AdaptiveEngine`.
6. **Adattamento** (`adaptive_engine.AdaptiveEngine`): ogni punteggio viene aggregato per `topic_hint`; la prossima domanda viene scelta dando priorità ai topic con media bassa (topic deboli), poi ai topic mai visti.
7. **Fine sessione** (`session._save_session` → `report_generator.save_report`): viene generato un report con media generale, argomenti da rivedere/padroneggiati, e salvato sia in Markdown sia in PDF; il tutto viene persistito nella tabella `Session` (`qa_log`, `score_total`, `report_path`).
8. **Storico** (`history.py`): lo studente può rivedere tutte le sessioni passate, riaprire il dettaglio Q&A, rigenerare un PDF mancante, o generare **appunti sintetici** (`notes_generator.generate_notes_from_log`) mirati sugli errori fatti.
9. **Appunti generali** (`exam.py` → `notes_generator.generate_notes_pdf_from_materials`): in qualsiasi momento si possono generare appunti completi a partire da tutti i PDF caricati per l'esame, non solo da una sessione.

Parallelamente a tutto questo esiste un **layer API REST equivalente** (`backend/api/`) che espone lo stesso flusso (auth → esami → sessione → tutor → adaptive engine → report) tramite endpoint FastAPI, pensato per un frontend disaccoppiato o integrazioni esterne. Streamlit, nell'implementazione attuale, chiama direttamente le funzioni Python degli agenti (non passa dalle API), mentre l'API REST è un'interfaccia parallela pronta all'uso.

---

## 2. Frontend Streamlit (`app/`)

### `main.py` — Entry point
Punto di ingresso dell'app (`streamlit run app/main.py`).
- **Inizializza il DB** con `init_db()` prima di ogni altra cosa.
- **Configura la pagina** (`st.set_page_config`) e inietta il CSS globale (tema scuro, font Syne/Inter, badge, card).
- **Inizializza `session_state`** con i valori di default (`authenticated`, `current_page`, `current_exam`, `current_session`, ecc.) — necessario perché Streamlit ricarica lo script a ogni interazione e senza `session_state` si perderebbe lo stato.
- **Login automatico da cookie**: se l'utente non è autenticato in sessione, controlla se c'è un `?token=` in query string (verificato con `verify_token`) oppure lancia `render_cookie_autologin_probe()` per andare a leggere il cookie lato browser.
- **Router**: in base a `st.session_state.current_page`, importa e chiama la funzione `render()` della pagina corrispondente (`login`, `upload`, `session`, `history`, `exam`).

### `pages/login.py` — Autenticazione
- `_hash_password(pwd)`: hash SHA-256 della password (nessuna password in chiaro salvata).
- `_login(username, password)`: verifica le credenziali contro il DB; se valide, popola `session_state` (`authenticated`, `student_id`, `username`) e imposta `current_page = "upload"`.
- `_register(username, password, confirm)`: valida i vincoli (username ≥3 caratteri, password ≥6, conferma coincidente, username univoco), crea il nuovo `Student` nel DB.
- `render()`: disegna la UI con due tab (Accedi/Registrati); dopo login/registrazione riuscita chiama `get_or_create_token` + `render_set_cookie` per abilitare il login persistente.

### `pages/upload.py` — Dashboard esami
- `_require_auth()`: guardia che reindirizza al login se non autenticato.
- `_get_exams`, `_create_exam`, `_rename_exam`, `_delete_exam`: CRUD sugli esami dello studente.
- `_get_exam_materials`, `_create_material_record`, `_delete_material`: CRUD sui materiali (PDF) associati a un esame.
- `_session_count`, `_avg_score`: statistiche aggregate per esame (numero sessioni, media voti) mostrate nelle card.
- `_close_orphan_sessions(exam_id)`: chiude (`ended_at = now`) tutte le sessioni rimaste "appese" (mai terminate) prima di aprirne una nuova, per non sporcare lo storico.
- `_navbar()`: barra superiore con logo, link a "Storico" e pulsante "Esci" (che invalida il token persistente e cancella il cookie).
- `render()`: mostra il form di creazione esame e la griglia di card (3 per riga) con nome, data, numero fonti e pulsanti Apri/Modifica/Elimina.
- `_render_notes_panel(exam, student_id)`: (funzione ausiliaria, generazione di appunti dal materiale RAG completo di un esame con download in `.md`).

### `pages/exam.py` — Dettaglio esame
- `_close_orphan_sessions(exam_id)`: stessa logica di `upload.py`, richiamata prima di avviare una nuova sessione da questa pagina.
- `render()`: mostra 4 azioni principali per l'esame selezionato:
  - **Avvia sessione**: resetta lo stato della sessione in `session_state` e naviga a `session.py`.
  - **Aggiungi fonti (PDF)**: `st.file_uploader` multiplo; ogni file viene salvato su disco e passato a `ingest_pdf`; il materiale indicizzato viene registrato come riga `Material` nel DB. Un contatore (`upload_counter`) forza la ricreazione del widget per evitare che Streamlit ripresenti gli stessi file già caricati.
  - **Crea appunti (.pdf)**: chiama `notes_generator.generate_notes_pdf_from_materials` su tutti i materiali dell'esame.
  - **Storico**: naviga a `history.py`.

### `pages/session.py` — Il cuore dell'esperienza interattiva
Questo file orchestra l'intero ciclo socratico lato UI.
- `_attempt_to_log_entry(attempt, final_score)`: converte un oggetto `QuestionAttempt` (dataclass del tutor) in un dizionario "piatto" pensato per essere serializzato in `qa_log` e riletto facilmente da `history.py`.
- `_navbar()`: barra con nome esame e pulsante "Esci" che, se la sessione è a metà, la marca come interrotta (`_mark_session_interrupted`) invece di perdere silenziosamente i dati.
- `_mark_session_interrupted(sess)`: imposta `ended_at = now` e salva il `qa_log` parziale, **senza** impostare `score_total` — così in storico la sessione appare "Non completata" ma con le domande già fatte visibili, non vuota.
- `_progress_bar`, `_score_badge`, `_diff_badge`: helper di rendering (barra di avanzamento, badge colorato per punteggio/difficoltà).
- `_create_db_session(exam_id)`: crea la riga `Session` nel DB all'avvio del quiz.
- `_save_session(session_id, attempts, engine, exam)`: a fine sessione, genera il report (`engine.generate_session_report()`), lo salva su disco (`save_report`), e aggiorna la riga `Session` (`ended_at`, `score_total`, `qa_log`, `report_path`). Contiene un controllo esplicito per **evitare doppi salvataggi** in caso di rerun multipli di Streamlit.
- `_render_quiz_generation()`: prima fase — slider per il numero di domande, pulsante "Genera domande" che chiama `generate_quiz`, crea l'`AdaptiveEngine` e la sessione DB, popola `session_state.current_session`.
- `_render_active_session()`: la macchina a stati del loop socratico:
  - stato `idle` → `AdaptiveEngine.pick_next_question` sceglie la domanda, si istanzia un nuovo `SocraticTutor` e si passa a `answer1`;
  - stato `answer1` → text area per la prima risposta, invio → `tutor.submit_answer_1()`;
  - stato `answer2` → mostra la domanda guida e il feedback positivo, text area per la seconda risposta → `tutor.submit_answer_2()`;
  - stato `evaluated` → mostra punteggio, motivazione, punti corretti/mancanti; offre il pulsante di contestazione (→ `tutor.submit_contestation()`) e "Prossima domanda" (→ `_close_and_advance`);
  - stato `contested` → mostra l'esito dell'arbitraggio e "Prossima domanda".
- `_close_and_advance(engine, current_q, final_score, sess)`: chiude il tutor (`tutor.close()`), aggiorna l'`AdaptiveEngine` (`record_answer`), aggiorna `sess["remaining"/"attempts"/"scores"]`, e se non restano domande salva la sessione.
- `_render_session_complete()`: schermata finale con verdetto (🏆/👍/📚), media, riepilogo domanda per domanda, download del report PDF (con fallback per rigenerarlo se manca), e navigazione verso storico o nuova sessione.
- `render()`: entry point della pagina — instrada tra le tre fasi (generazione quiz, sessione attiva, sessione completata) in base allo stato corrente.

### `pages/history.py` — Storico sessioni
- `_rebuild_report_payload(sess)` e `_regenerate_pdf_report(session_id, exam_name)`: permettono di **rigenerare** un report PDF perso partendo dal solo `qa_log` salvato, ricostruendo un payload minimo compatibile con `save_report`.
- `_get_all_exams`, `_get_sessions`: query al DB; `_get_sessions` inoltre **pulisce automaticamente** le sessioni "avviate ma senza voto e senza log" (rumore lasciato da sessioni abbandonate immediatamente).
- `_delete_session`, `_close_session`: rispettivamente elimina una sessione o la marca manualmente come conclusa (`ended_at = now`) senza cancellarla — utile per sessioni bloccate in stato "In corso".
- `_is_orphan(sess)`: una sessione è orfana se `ended_at is None`, indipendentemente da quanto tempo sia passato.
- `_format_duration`, `_score_color`, `_verdict_emoji`: helper di formattazione/visualizzazione.
- `_render_session_detail(sess)` + `_is_valid_attempt`: espande il dettaglio Q&A di una sessione, mostrando risposta 1, domanda guida, risposta 2, motivazione ed eventuale esito della contestazione.
- `_render_notes_panel(sess)`: genera (con cache in `session_state`) appunti sintetici da una singola sessione tramite `notes_generator.generate_notes_from_log`.
- `render()`: pagina principale — selezione esame, statistiche aggregate (sessioni totali, completate, media, miglior voto), lista sessioni con azioni (dettaglio, appunti, download/rigenerazione PDF, chiusura, eliminazione).

---

## 3. Backend — Agenti AI (`backend/agents/`)

### `ingestor.py` — Pipeline RAG (ingestione e recupero)
- `_get_sentence_transformer()`: carica una sola volta (singleton) il modello di embedding locale `all-MiniLM-L6-v2`.
- `LocalEmbeddingFunction`: classe che implementa l'interfaccia `EmbeddingFunction` di ChromaDB, delegando all'oggetto sopra il calcolo dei vettori — permette embeddings **locali, gratuiti e offline**.
- `get_collection(student_id, exam_id)`: restituisce (creandola se serve) la collection ChromaDB isolata per quello studente+esame (`student_{id}_exam_{id}`) — garantisce che i dati di uno studente non si mischino mai con quelli di un altro.
- `chunk_text(text, chunk_size, overlap)`: divide un testo in blocchi di ~500 parole con 50 di overlap, per non spezzare un concetto a metà tra due chunk.
- `ingest_pdf(pdf_path, student_id, exam_id)`: estrae il testo pagina per pagina con `pypdf`, scarta le pagine senza testo (solleva `ValueError` se **nessuna** pagina è estraibile, es. PDF scansionato), spezza il testo in chunk, li invia a ChromaDB in batch da 100 con i relativi metadati (pagina, nome file). Ritorna statistiche (`pages`, `chunks`, `collection`).
- `retrieve_chunks(query, student_id, exam_id, n_results)`: ricerca semantica — dato un testo di query, ritorna gli `n_results` chunk più simili. Usato da quiz, tutor e notes.
- `retrieve_chunks_by_source(student_id, exam_id, source_file, limit)`: variante che filtra per singolo file sorgente (usata per generare appunti "per fonte" invece che sull'intero materiale).
- `delete_exam_collection(student_id, exam_id)`: elimina l'intera collection ChromaDB quando un esame viene cancellato, ignorando l'errore se la collection non esiste già.

### `quiz_generator.py` — Generazione domande
- `Question` (dataclass): id, testo, difficoltà, `topic_hint`.
- `QuizResult` (dataclass): lista di `Question` + metadati (fonte, numero domande, versione prompt, exam/student id).
- `_load_prompt_template()`: legge il file di prompt versionato da disco.
- `_parse_llm_response(raw)`: parser **robusto** dell'output del modello — rimuove backtick/markdown, isola il blocco `{...}`, e se il JSON non è valido tenta una riparazione automatica (virgole finali, virgolette singole) prima di sollevare un errore dettagliato.
- `_make_quiz_agent(model_name)`: istanzia l'agente Agno con Groq/Llama, con istruzioni di sistema che impongono JSON puro.
- `_is_rate_limit_error(raw)`: rilevamento euristico di risposte di errore da rate limit dell'API.
- `generate_quiz(student_id, exam_id, topic_query, n_questions, n_chunks, source_name, model_name)`: funzione principale — recupera i chunk (RAG), compone il prompt, interroga l'agente **con retry indefinito** finché non ottiene un JSON valido con abbastanza domande, e restituisce un `QuizResult`.
- `quiz_to_dict`, `quiz_to_json`: utilità di serializzazione.

### `socratic_tutor.py` — Loop socratico (guida, valutazione, contestazione)
- `TurnState` (Enum): stati del ciclo per una singola domanda (`WAITING_ANSWER_1`, `WAITING_ANSWER_2`, `EVALUATED`, `CONTESTED`, `CLOSED`).
- `EvaluationResult`, `ContestationResult` (dataclass): strutture tipizzate per l'esito della valutazione e dell'eventuale contestazione.
- `QuestionAttempt` (dataclass): stato completo di una domanda (testo, risposte, domanda guida, valutazione, contestazione); la property `final_score` restituisce il voto post-contestazione se presente, altrimenti quello della valutazione iniziale.
- `_load_prompt(version_name)`: carica un prompt versionato da `prompts/`.
- `_parse_json(raw)`: pulizia e parsing JSON dell'output LLM.
- `_is_non_answer(text)` + `NON_ANSWER_PATTERNS`: rileva risposte tipo "non so"/"boh"/"idk" via regex, per applicare severità automatica.
- `_apply_severity_guardrails(attempt, evaluation)`: se la **seconda** risposta è una non-risposta, forza il punteggio a 0 indipendentemente da cosa abbia detto il modello valutatore.
- `_has_no_real_gaps(missing_points)` + `NO_GAPS_PATTERNS`: verifica se la lista di lacune indicate dal valutatore è vuota o dichiara esplicitamente "nessuna lacuna".
- `_apply_consistency_guardrails(evaluation)`: se non ci sono lacune reali ma il punteggio è sotto 9, lo **corregge automaticamente a 9** — evita l'incoerenza "tutto corretto ma voto 6".
- `_guide_agent`, `_eval_agent`, `_contest_agent`: factory dei tre agenti Agno specializzati.
- `_generate_guiding_question`, `_evaluate`, `_re_evaluate_after_contestation`: le tre funzioni che chiamano rispettivamente Guide/Eval/Contest Agent, ciascuna con retry su rate limit (con parsing del tempo di attesa suggerito, `_parse_retry_after`) e retry generico su eccezioni.
- **Classe `SocraticTutor`** (l'API pubblica usata dal frontend/API):
  - `start(question_data)`: inizializza un `QuestionAttempt` e pre-carica i chunk RAG rilevanti per quella domanda.
  - `submit_answer_1(answer)`: salva la risposta, chiama il Guide Agent, passa allo stato `WAITING_ANSWER_2`.
  - `submit_answer_2(answer)`: salva la risposta, chiama l'Eval Agent (con guardrail), passa a `EVALUATED`.
  - `submit_contestation(argumentation)`: chiama il Contest Agent, passa a `CONTESTED`.
  - `close()`: valida che lo stato sia `EVALUATED`/`CONTESTED` e marca `CLOSED`, restituendo l'`attempt` definitivo.
  - `to_dict`/`to_json`: serializzazione per la persistenza.
  - `_assert_state(expected)`: guardia interna che impedisce transizioni di stato non valide (es. chiamare `submit_answer_2` prima di `submit_answer_1`).

### `adaptive_engine.py` — Personalizzazione del percorso
- `TopicStats` (dataclass): punteggi accumulati per un singolo topic; `avg_score`, `n_attempts`, e `is_weak` (media <6, oppure un solo tentativo con voto <5).
- `SessionStats` (dataclass): aggrega `TopicStats` per tutti i topic della sessione; espone `overall_avg`, `weak_topics`, `strong_topics`.
- **Classe `AdaptiveEngine`**:
  - `record_answer(question_id, topic, score)`: registra un risultato (con clamp difensivo 0-10) nelle statistiche del topic corrispondente.
  - `pick_next_question(remaining)`: logica di scelta a 3 livelli di priorità — 1) domande su topic già rilevati come deboli, 2) domande su topic mai visti, 3) prima domanda rimanente disponibile.
  - `generate_session_report()`: costruisce il dizionario di report finale (media, breakdown per topic ordinato per punteggio crescente, topic deboli/forti, sintesi testuale).
  - `to_json()`: serializza lo stato corrente (utile per debug/salvataggi intermedi).
- `_build_summary(stats)`: funzione modulo-livello che genera il testo di sintesi leggibile (es. "Ottima prestazione complessiva. Argomenti da rivedere: ...").

### `report_generator.py` — Report di sessione (MD + PDF)
- `_pdf_safe_text(value)`: normalizza qualunque testo in caratteri Latin-1 supportati da FPDF (sostituisce emoji/simboli unicode con equivalenti ASCII, es. "✅"→"OK").
- `generate_markdown(report, session_id, exam_name)`: costruisce il report in Markdown (tabelle risultato complessivo, performance per argomento, aree da rivedere/punti di forza, sintesi).
- **Classe `_ReportPDF(FPDF)`**: sottoclasse con `header()`/`footer()` personalizzati (titolo ricorrente, numero di pagina).
- `_add_section_title`, `_add_body`: helper di formattazione PDF.
- `generate_pdf(report, session_id, exam_name)`: costruisce il PDF con titolo, riquadro voto colorato per fascia, tabella performance per topic, sezioni aree da rivedere/punti di forza/sintesi.
- `save_report(report, session_id, exam_name)`: salva sia il `.md` sia il `.pdf` su disco in `reports/{student_id}_{exam_id}_{session_id}.*` e ne ritorna i path.

### `notes_generator.py` — Appunti di ripasso (MD + PDF)
- `_load_prompt_template()`, `_is_error_response`, `_parse_error_retry_time`: analoghi a quanto visto negli altri agenti, per caricare il prompt e gestire errori/rate limit del modello.
- `_build_log_summary(attempts)`: trasforma il log di una sessione in un riassunto testuale (domanda, topic, voto, risposta, lacune) da passare come contesto al modello.
- `_extract_weak_topics(attempts)`: estrae i topic con voto <6 dalla sessione, deduplicati mantenendo l'ordine.
- `_pdf_safe_text`, `_strip_inline`, `_clean_chunk`, `_clean_chunks`: pulizia aggressiva del testo (rimozione di artefatti LaTeX/markdown corrotti dai PDF sorgente, righe con troppo rumore/pochi caratteri alfabetici) per evitare che il modello "veda" e ripeta rumore di estrazione.
- `_validate_notes(notes)`: verifica euristiche di qualità (lunghezza minima 700 parole, presenza di sezioni obbligatorie come "## ..." e "> **Definizione", assenza di LaTeX corrotto) prima di accettare l'output del modello.
- `_run_with_retry(agent, prompt)`: ciclo di generazione **con retry indefinito** finché la risposta non passa la validazione.
- **Classe `_NotesPDF(FPDF)`**: PDF con header/footer personalizzati e gestione robusta degli "a capo pagina" (`check_page_break`, `ensure_space`) per evitare sovrapposizioni di testo.
- `_render_markdown(pdf, text_md)`: **motore di rendering Markdown→PDF fatto a mano** — riconosce e stilizza titoli H2/H3/H4, separatori, blockquote (definizioni/teoremi con bordo blu), bullet e sotto-bullet, liste numerate, paragrafi normali.
- `_add_front_page(pdf, title, subtitle)`: genera un frontespizio con banda colorata, titolo, sottotitolo e data.
- `generate_notes(student_id, exam_id, ...)`: genera appunti in Markdown da tutto il materiale RAG di un esame.
- `generate_notes_pdf(...)`: come sopra ma restituisce direttamente un PDF completo (frontespizio + contenuto renderizzato).
- `generate_notes_pdf_from_materials(student_id, exam_id, materials, ...)`: genera un PDF con **una sezione per ogni file** caricato (recupera i chunk specifici di quel file, li ripulisce, e li invia al modello), con fallback a una sintesi generale se nessun materiale ha contenuto recuperabile.
- `generate_notes_from_log(attempts, ...)`: genera appunti **mirati sugli errori** di una sessione specifica, opzionalmente arricchiti con contesto RAG sui topic deboli (`enrich_with_rag`).

---

## 4. Backend — Persistenza e API (`backend/db/`, `backend/models/`, `backend/api/`)

### `db/models.py` — Schema dati (SQLAlchemy ORM)
- `now_utc()`: timestamp UTC coerente per tutti i record.
- **`Student`**: utente registrato (`username`, `password_hash`, `session_token` per il login persistente); relazione 1-a-N con `Exam` (cascade delete).
- **`Exam`**: un esame/corso dello studente (`name`); relazioni 1-a-N con `Session` e `Material` (cascade delete).
- **`Material`**: un PDF caricato e indicizzato (`filename`, `stored_path`, `chunks_count`, `pages_count`).
- **`Session`**: una sessione di studio (`started_at`, `ended_at`, `score_total`, `qa_log` JSON, `report_path`) — è la tabella centrale collegata sia allo storico sia ai report.
- `init_db()`: crea tutte le tabelle se non esistono e applica la migrazione leggera `_ensure_session_token_column()`.
- `_ensure_session_token_column()`: aggiunge a runtime la colonna `session_token` sui DB creati prima dell'introduzione del login persistente (SQLite non supporta `ALTER TABLE ADD COLUMN ... UNIQUE`, quindi il vincolo di unicità è garantito solo applicativamente tramite `secrets.token_urlsafe`).

### `models/schemas.py` — Contratti dati delle API (Pydantic)
Definisce le classi `Request`/`Response` per ogni endpoint FastAPI, raggruppate per dominio: `RegisterRequest`/`LoginRequest`/`AuthResponse` (auth), `ExamCreate`/`ExamResponse`/`ExamListResponse`/`IngestResponse` (esami), `QuizGenerateRequest`/`QuestionOut`/`QuizGenerateResponse` (quiz), `SessionCreate`/`SessionResponse`/`SessionListResponse` (sessioni), `TutorStartRequest/Response`, `Answer1/2Request/Response`, `ContestRequest/Response`, `CloseQuestionRequest/Response` (ciclo socratico step-by-step), `NextQuestionRequest/Response` (adaptive engine), `SessionCloseRequest`, `TopicBreakdown`, `SessionReportResponse` (report), `ErrorResponse`. Ogni classe valida automaticamente i vincoli (es. `score: int = Field(..., ge=0, le=10)`).

### `session_cookie.py` — Login persistente
- `get_or_create_token(student_id)`: restituisce (o genera con `secrets.token_urlsafe(32)`) il token persistente salvato su `Student.session_token`.
- `verify_token(token)`: recupera lo `Student` associato a un token, se esiste.
- `invalidate_token(student_id)`: azzera il token lato server al logout esplicito.
- `render_set_cookie(token)` / `render_clear_cookie()`: iniettano piccoli snippet JS (`st.components.v1.html`) per scrivere/cancellare il cookie `sc_token` nel browser (durata ~10 anni, con `Max-Age`).
- `render_cookie_autologin_probe()`: JS che legge il cookie lato client e, se presente e non già passato come query param, ricarica la pagina aggiungendo `?token=...`, permettendo al backend Python (che non legge i cookie direttamente in Streamlit) di completare l'auto-login.

### `api/auth.py` — Endpoint autenticazione
- `_hash_password`, `_get_student_by_username`: helper condivisi.
- `POST /auth/register`: crea un nuovo `Student` (409 se username già in uso).
- `POST /auth/login`: verifica credenziali e ritorna `student_id` (401 se non valide).
- `POST /auth/logout`: placeholder stateless (il logout reale avviene lato client).

### `api/exams.py` — Endpoint gestione esami e upload
- `_get_exam_or_404`, `_enrich_exam` (aggiunge `n_sessions`/`avg_score` calcolati): helper interni.
- `GET /exams`: lista esami con statistiche aggregate.
- `POST /exams`: crea un esame vuoto.
- `DELETE /exams/{id}`: elimina esame (cascade su sessioni/materiali) + collection ChromaDB associata.
- `POST /exams/{id}/ingest`: riceve un PDF via upload, lo salva su disco e lo indicizza con `ingest_pdf`.

### `api/sessions.py` — Endpoint del ciclo di sessione (equivalente REST di `session.py`)
Espone, uno per uno, tutti gli step gestiti internamente da `session.py`/`socratic_tutor.py`/`adaptive_engine.py`, usando due dizionari in-memory (`_active_tutors`, `_active_engines`) per mantenere lo stato tra una chiamata e l'altra dello stesso processo:
- `POST /sessions`: apre sessione, istanzia `AdaptiveEngine`.
- `POST /sessions/{id}/quiz`: genera il quiz.
- `POST /sessions/{id}/tutor/start|answer1|answer2|contest|close`: step del `SocraticTutor` uno a uno.
- `_append_attempt_to_log`: appende il tentativo chiuso al `qa_log` della `Session` nel DB.
- `POST /sessions/{id}/next-question`: chiede all'`AdaptiveEngine` la prossima domanda tra quelle rimanenti.
- `POST /sessions/{id}/close`: genera il report finale, aggiorna la `Session` (`ended_at`, `score_total`, `report_path`), rimuove l'engine dalla memoria.
- `GET /sessions/{id}` e `GET /sessions?exam_id=`: lettura di dettaglio/lista.

### `api/main.py` — Bootstrap FastAPI
- `lifespan(app)`: hook di avvio che chiama `init_db()` prima di accettare richieste.
- Configura CORS per permettere le chiamate dal frontend Streamlit (`localhost:8501`).
- Registra i tre router (`auth`, `exams`, `sessions`) e un endpoint `/health` di controllo stato.

---

## 5. Prompt versionati (`backend/agents/prompts/`)

| File | Agente | Cosa impone |
|---|---|---|
| `quiz_generator_v1.txt` | QuizGeneratorAgent | JSON puro, N domande, difficoltà bilanciata, divieto di copiare testo dal materiale |
| `socratic_tutor_guide_v1.txt` | SocraticGuideAgent | Non rivelare mai la risposta corretta; riconoscere punti giusti; domanda aperta |
| `socratic_tutor_eval_v1.txt` | EvaluatorAgent | Scala di voto 0-10, regole di severità sulle non-risposte, regole di coerenza voto/lacune |
| `socratic_tutor_contest_v1.txt` | ContestationAgent | Rivalutazione imparziale basata solo sul materiale, esito tra valido/parzialmente valido/non valido |
| `notes_generator_v1.txt` | NotesGeneratorAgent | Struttura obbligatoria (introduzione, definizioni, teoremi, esempi, collegamenti, note, riepilogo), divieto di copiare rumore dai frammenti grezzi |

---

## 6. Riepilogo rapido "chi chiama chi"

- **Streamlit pages** → chiamano direttamente le funzioni degli **agenti** (`ingestor`, `quiz_generator`, `socratic_tutor`, `adaptive_engine`, `report_generator`, `notes_generator`) e il layer **`db/models`**.
- **FastAPI routers** → stessa cosa, ma esposta come endpoint REST, con stato in-memory per tutor/engine attivi.
- **Tutti gli agenti AI** → passano sempre da `ingestor.retrieve_chunks[_by_source]` per ottenere il contesto (RAG) prima di interrogare l'LLM.
- **`socratic_tutor`** → è l'unico agente che coinvolge **tre** agenti Agno diversi in sequenza (guida, valutazione, eventuale contestazione) sulla stessa domanda.
- **`adaptive_engine`** → non fa mai chiamate LLM: è pura logica Python che decide l'ordine delle domande in base ai punteggi già registrati.
