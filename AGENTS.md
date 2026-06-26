# Study Coach — Documentazione Tecnica e Funzionale

Questa documentazione fornisce un'analisi dettagliata di ogni componente del sistema Study Coach, descrivendone lo scopo, le interazioni, la logica interna e le scelte architetturali.

---

## 1. Architettura e Flusso Principale

### Flusso Principale dell'Agente
Il sistema trasforma materiale didattico statico in un'esperienza di apprendimento interattiva e adattiva attraverso le seguenti fasi:

1.  **Ingestion & RAG**: Lo studente carica un PDF. L'agente `ingestor` estrae il testo, lo divide in chunk semantici e crea embeddings locali salvandoli in ChromaDB. Questo permette all'AI di avere una "memoria a lungo termine" specifica per l'esame.
2.  **Generazione Quiz**: Basandosi sui contenuti estratti, il `quiz_generator` crea domande calibrate per verificare la comprensione reale.
3.  **Loop Socratico**: Invece di correggere subito, il sistema usa un approccio pedagogico:
    - Lo studente risponde.
    - Il `SocraticTutor` (Guide Agent) pone una domanda guida per stimolare il ragionamento se la risposta è incompleta o errata.
    - Dopo il secondo tentativo, l' `EvalAgent` valuta e assegna un punteggio.
    - Lo studente può contestare il voto tramite il `ContestAgent`.
4.  **Adattamento**: L'`AdaptiveEngine` analizza i risultati. Se lo studente fallisce su un topic, il sistema proporrà più domande su quell'argomento per colmare le lacune.
5.  **Output Finali**: Al termine vengono generati report di sessione e appunti personalizzati focalizzati sulle debolezze riscontrate.

---

## 2. Analisi Dettagliata dei File (Backend)

### `backend/db/models.py`
- **A cosa serve**: Definisce lo schema del database relazionale (SQLite) tramite SQLAlchemy e gestisce la persistenza dei dati.
- **Con chi interagisce**: Interagisce con tutti i router API e le pagine Streamlit per la lettura/scrittura dei dati persistenti.
- **Funzioni principali**:
    - `now_utc()`: Genera timestamp UTC. *Serve a garantire coerenza temporale nei log.*
    - `init_db()`: Crea le tabelle nel DB. *Serve ad assicurare che il database sia pronto all'avvio.*
    - `Student`, `Exam`, `Material`, `Session`: Classi ORM. *Servono a mappare le tabelle del DB in oggetti Python facilitando la manipolazione dei dati.*

### `backend/agents/ingestor.py`
- **A cosa serve**: Gestisce la pipeline di Retrieval Augmented Generation (RAG), occupandosi di indicizzazione e recupero di testo dai PDF.
- **Con chi interagisce**: Riceve file dalle API/UI e fornisce chunk di testo ai vari agenti (quiz, tutor, notes).
- **Funzioni principali**:
    - `LocalEmbeddingFunction`: Genera vettori localmente. *Serve a garantire privacy e funzionamento offline senza costi API per gli embeddings.*
    - `chunk_text()`: Divide il testo in blocchi con overlap. *Serve a mantenere il contesto semantico durante la ricerca vettoriale.*
    - `ingest_pdf()`: Estrae testo dai PDF e lo salva in ChromaDB. *Serve a rendere il materiale di studio consultabile dall'AI.*
    - `retrieve_chunks()`: Esegue la ricerca semantica. *Serve a fornire all'LLM solo le informazioni pertinenti, riducendo le allucinazioni.*
    - `delete_exam_collection()`: Elimina i dati vettoriali. *Serve a mantenere pulito il database quando un esame viene rimosso.*

### `backend/agents/quiz_generator.py`
- **A cosa serve**: Genera domande d'esame strutturate partendo dal materiale caricato.
- **Con chi interagisce**: Utilizza `ingestor.py` per i dati e comunica con `sessions.py` o le pagine Streamlit.
- **Funzioni principali**:
    - `_make_quiz_agent()`: Inizializza l'agente Agno per i quiz. *Serve a configurare l'LLM con le istruzioni specifiche per la generazione.*
    - `generate_quiz()`: Coordina RAG e LLM per creare il quiz. *Serve a generare domande pertinenti e calibrate sul materiale.*
    - `_parse_llm_response()`: Converte il testo dell'AI in oggetti Python. *Serve a garantire che il frontend riceva dati strutturati e validi.*

### `backend/agents/socratic_tutor.py`
- **A cosa serve**: Gestisce l'interazione pedagogica (metodo socratico) e la valutazione delle risposte.
- **Con chi interagisce**: Utilizza `ingestor.py` per verificare la correttezza e comunica con il frontend per gestire il dialogo.
- **Funzioni principali**:
    - `_guide_agent()`, `_eval_agent()`, `_contest_agent()`: Creano agenti specializzati. *Serve a separare le responsabilità (guida vs valutazione) migliorando la precisione.*
    - `submit_answer_1()`: Gestisce il primo tentativo. *Serve a stimolare il ragionamento senza dare la soluzione.*
    - `submit_answer_2()`: Gestisce il secondo tentativo e la valutazione finale. *Serve a chiudere il loop con un feedback oggettivo.*
    - `submit_contestation()`: Gestisce le obiezioni dello studente. *Serve a garantire equità e trasparenza nel processo di valutazione.*

### `backend/agents/adaptive_engine.py`
- **A cosa serve**: Algoritmo che analizza le performance e personalizza il percorso di studio.
- **Con chi interagisce**: Riceve dati da `socratic_tutor.py` e decide la prossima mossa per lo studente.
- **Funzioni principali**:
    - `record_answer()`: Aggiorna le statistiche per topic. *Serve a tracciare dove lo studente è forte o debole.*
    - `pick_next_question()`: Seleziona la domanda successiva. *Serve a implementare l'apprendimento adattivo, insistendo sulle lacune.*
    - `generate_session_report()`: Crea un riassunto delle performance. *Serve a dare un feedback immediato allo studente a fine sessione.*

### `backend/agents/report_generator.py` e `notes_generator.py`
- **A cosa servono**: Generano documenti finali (PDF/Markdown) per lo studio offline e il ripasso.
- **Con chi interagiscono**: Leggono i log dal DB e i contenuti da ChromaDB.
- **Funzioni principali**:
    - `save_report()`: Genera e salva il report di sessione. *Serve a rendere persistenti i risultati ottenuti dallo studente.*
    - `generate_notes_pdf_from_materials()`: Crea un intero libro di appunti dai PDF caricati. *Serve a fornire materiale di studio sintetizzato dall'AI.*
    - `generate_notes_from_log()`: Crea appunti basati sugli errori fatti. *Serve a focalizzare il ripasso esattamente dove serve.*

### `backend/api/auth.py`, `exams.py`, `sessions.py`
- **A cosa servono**: Definiscono gli endpoint FastAPI per il sistema.
- **Con chi interagiscono**: Fanno da ponte tra il frontend e la logica di business/agenti.
- **Funzioni principali**:
    - `register()`/`login()`: Gestiscono l'accesso. *Serve a isolare i dati tra diversi studenti.*
    - `ingest_pdf_endpoint()`: Riceve i file. *Serve ad avviare la pipeline di ingestion via API.*
    - `create_session()`/`next_question()`: Gestiscono il flusso della sessione. *Serve a mantenere lo stato dell'interazione.*

---

## 3. Analisi Dettagliata dei File (Frontend)

### `app/main.py`
- **A cosa serve**: Entry point dell'applicazione Streamlit. Gestisce il routing tra le pagine e il CSS globale.
- **Con chi interagisce**: Carica le varie pagine del modulo `app/pages/`.
- **Funzioni principali**:
    - Inizializzazione `session_state`: Configura le variabili globali. *Serve a mantenere lo stato dell'utente e della sessione tra i vari refresh.*

### `app/pages/login.py`
- **A cosa serve**: Gestisce l'interfaccia di autenticazione.
- **Con chi interagisce**: Chiama i modelli DB per verificare le credenziali.
- **Funzioni principali**:
    - `render()`: Disegna la UI di login/registrazione. *Serve a fornire un punto d'accesso sicuro al sistema.*

### `app/pages/upload.py` e `exam.py`
- **A cosa servono**: Gestiscono la creazione degli esami e il caricamento dei materiali.
- **Con chi interagiscono**: Chiamano `ingestor.py` per elaborare i PDF.
- **Funzioni principali**:
    - `render()`: Mostra la dashboard degli esami e il widget di upload. *Serve a permettere all'utente di gestire il proprio piano di studi.*

### `app/pages/session.py`
- **A cosa serve**: L'interfaccia principale dell'interrogazione socratica.
- **Con chi interagisce**: Orchestratore principale che usa `SocraticTutor`, `AdaptiveEngine` e `QuizGenerator`.
- **Funzioni principali**:
    - `_render_active_session()`: Gestisce il dialogo dinamico con i vari agenti. *Serve a fornire l'esperienza di studio interattiva.*
    - `_close_and_advance()`: Salva il progresso e passa alla domanda successiva. *Serve a garantire la fluidità del percorso adattivo.*

---

## 4. Scelte Architetturali e AI

### Perché un Sistema Multi-Agente?
Abbiamo scelto di utilizzare il framework **Agno** per implementare un'architettura multi-agente. Invece di un unico prompt gigante, abbiamo diviso le responsabilità:
- **Guide Agent**: Specializzato nel non dare risposte, ma nel fare domande (metodo socratico).
- **Eval Agent**: Specializzato nella valutazione oggettiva basata sul testo.
- **Contest Agent**: Un "arbitro" terzo che interviene solo se lo studente contesta, garantendo imparzialità.
*Questa separazione riduce drasticamente le allucinazioni e permette di dare istruzioni molto più precise a ogni componente.*

### Perché la RAG (Retrieval Augmented Generation)?
L'uso di **ChromaDB** e embeddings locali permette al sistema di rispondere basandosi *solo* sul materiale caricato. Questo è fondamentale in ambito universitario dove la precisione terminologica è essenziale e l'AI non deve inventare concetti non presenti nel programma.

### Uso dei Coding Agents
Durante lo sviluppo, abbiamo utilizzato agenti di coding (come Junie) per:
- **Refactoring**: Per separare la logica Streamlit da quella degli agenti, seguendo il principio di singola responsabilità.
- **Gestione Errori**: Implementazione di logica robusta per il parsing dei PDF e la gestione dei rate limit delle API.
- **Documentazione**: Generazione automatica di schemi e mapping delle funzioni.
Ogni scelta fatta dagli agenti è stata validata e contestualizzata per assicurare che il flusso logico rispettasse i requisiti pedagogici del progetto.

---

## 5. Note per l'Esame e Demo

**Domande frequenti e risposte:**
- **Scelte AI**: La scelta di Gemini e Agno è dettata dalla necessità di avere modelli veloci con finestre di contesto ampie, orchestrati in modo da mantenere lo stato della sessione in modo coerente.
- **Miglioramenti futuri**: Implementazione della persistenza su Redis per scalabilità e supporto a materiali multimediali (immagini/formule).

**Procedura Finale:**
1.  **Invio Email**: Una volta completato e documentato il progetto, si invia un'email al professore per organizzare una call di demo.
2.  **La Call**: Durante la call si effettua una demo live (caricamento PDF -> quiz -> sessione socratic -> report). Il professore valuta la solidità dell'architettura e l'uso sensato degli agenti.
3.  **Approvazione**: Se il progetto è approvato, il professore si prende alcuni giorni per assegnare il voto.
4.  **Parte Scritta**: Solo dopo l'approvazione del progetto è possibile sostenere la prova scritta.

---
*Documento aggiornato al 2026-06-26*
