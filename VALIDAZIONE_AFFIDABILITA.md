# Verifica di affidabilità dei materiali e dell'AI

Verifica del 12 ottobre 2026. Questo documento distingue i test del software dalle prove con un modello reale. I percorsi citati sono relativi alla radice del repository.

## 1. Materiali disponibili al tutor

| Caso riproducibile | Input e riferimento | Atteso | Ottenuto e prova |
|---|---|---|---|
| Due PDF nello stesso esame | `test/test_ingestor.py::test_multi_pdf_no_collision`; PDF A, PDF B e terzo file con stesso nome ma byte diversi | ID distinti, 2 + 3 + 3 chunk presenti | 8 ID distinti. `backend/agents/ingestor.py::ingest_pdf` usa SHA-256 dei byte, pagina e indice del chunk. |
| Selezione di una sola fonte | `test/test_ingestor.py::test_selected_material_queries_exclude_other_pdfs`; Bayes e matrici | Il tutor recupera solo Bayes quando è selezionato quel materiale | I tre percorsi di retrieval restituiscono solo Bayes; `verify_exam_material` verifica anche la selezione. |
| Indicizzazione già parziale | `test/test_ingestor.py::test_reingest_rejects_partial_existing_index`; si rimuove un ID Chroma, poi si ricarica lo stesso PDF | Nessuna statistica di successo | `ingest_pdf` confronta l'insieme degli ID attesi con quelli presenti e segnala indice incompleto. I chunk superstiti restano disponibili per diagnosi. |
| File alterato dopo il caricamento | `test/test_ingestor.py::test_material_verification_detects_changed_pdf_bytes`; si cambiano i byte del PDF | Verifica negativa | `verify_exam_material` ricalcola SHA-256 e segnala il file modificato. |

L'ingestione verifica gli ID presenti dopo l'inserimento e rimuove i chunk inseriti se il controllo fallisce. `verify_exam_material` confronta file, hash, righe `Material` e conteggi Chroma; le pagine prive di testo sono esplicitate nelle statistiche. Questi controlli danno evidenza di presenza e integrità tecnica, non garantiscono che OCR, suddivisione in chunk e ranking abbiano preservato ogni informazione semanticamente utile. Un arresto brusco durante un batch Chroma può ancora lasciare un indice parziale: la nuova verifica lo rileva al tentativo successivo, ma non lo ripara automaticamente.

## 2. Giudizi

`backend/agents/evaluation_validator.py` richiede voto intero 0–10, motivazione, punti corretti, punti mancanti e campo di miglioramento. Rifiuta liste di tipo errato, voto alto con troppe lacune, voto basso senza lacune, voto sufficiente senza punti corretti e 10 con lacune. `backend/agents/socratic_tutor.py` ritenta i giudizi non validi; il campo `missing_points` assente non può alzare il voto a 9. I test sono in `test/test_evaluation_validator.py` e `test/test_socratic_tutor.py`.

**Limite aperto:** questi controlli sono strutturali e basati su soglie. Non dimostrano da soli che la motivazione giustifichi il voto, che i punti corretti compaiano davvero nella risposta o che quelli mancanti siano fondati nel materiale. Non è quindi corretto dichiarare risolta la coerenza semantica completa; le voci K2.3–K2.6 e K2.9 in `ISSUES.md` restano aperte.

## 3. Prove con modello reale già registrate

`eval/cases/` contiene 60 casi con input, file di riferimento e SHA-256, atteso e motivazione umana per i 30 casi con voto. `eval/results/eval_20261008T081320Z.json` conserva output grezzi e metadati del run dell'8 ottobre 2026, modello `openai/gpt-oss-120b` tramite Groq. La prova è riproducibile con `uv run --extra dev python eval/run_eval.py --validate-only`; per una nuova esecuzione serve `GROQ_API_KEY`.

| Misura registrata | Risultato | Interpretazione |
|---|---:|---|
| Risposte reali | 60/60 | Il modello ha risposto in quel run; non indica assenza futura di guasti. |
| Voti confrontati con riferimento motivato | 30; errore assoluto medio 0,93 | 28/30 entro 2 punti; 13/30 esatti. |
| Pagine citate esattamente come atteso | 54/60 | Coincidenza dei numeri di pagina, non verifica di fedeltà delle singole affermazioni. |
| Richieste fuori materiale o dubbi non supportati | 9/9 con `supported=false` | Valido per i casi e il prompt del runner. |

**Casi negativi:** nel caso `K3.2-005` la risposta «Derivazione e integrale sono collegati» ha riferimento umano 6 (idea presente, formula assente, pagina 2) e voto del modello 2: quattro punti troppo severo. Nel caso `K3.2-016`, «La coda usa FIFO, la pila LIFO» ha riferimento umano 10 (distinzione completa, pagina 1) e voto del modello 6: quattro punti troppo severo. Nel caso fuori materiale `K3.2-out-01`, la richiesta sulla relatività generale rispetto alla dispensa di analisi ha prodotto `answer=null`, `supported=false` e nessuna pagina citata, come atteso. I risultati completi e i commenti dei casi sono nei JSON indicati.

**Limite decisivo:** `eval/run_eval.py` invia il testo completo delle tre dispense `.txt` direttamente a un agente Groq con un prompt di valutazione dedicato. Non esegue l'ingestione PDF, il retrieval Chroma, i prompt di produzione del tutor, le domande guida o il flusso completo di quiz e appunti. Le 15 voci denominate `retrieval` non misurano hit@k del recupero applicativo. Gli esiti `ok`/`parziale`/`ko` nei file dei casi sono etichette precompilate, non giudizi calcolati sull'output reale. Il run non prova quindi la qualità end-to-end del sistema; pertinenza dei chunk, fedeltà delle risposte, qualità delle domande guida e affidabilità dei voti del tutor in produzione richiedono ancora una prova rappresentativa sul flusso reale e revisione umana motivata. Le voci E6–E7 e K3 in `ISSUES.md` restano aperte.

## 4. Errori e interruzioni

| Condizione | Esito coperto dal codice e dai test | Limite |
|---|---|---|
| PDF non PDF, corrotto, protetto, scansionato o senza chunk utili | `test/test_ingestor.py`, `test/test_error_messages.py` e `test/test_api_exams.py` verificano errori riconoscibili e assenza di successo apparente. | OCR può perdere contenuto pur producendo testo. |
| Servizio AI indisponibile o con limite | `backend/agents/llm_errors.py`, `backend/error_messages.py` e test API distinguono HTTP 429 e altri errori; retry limitati. | Dipende dal provider e dalla sua disponibilità. |
| Output vuoto, incompleto o malformato | Parser e validatori rifiutano il risultato; `test/test_quality_controls.py`, `test/test_notes_generator.py` e `test/test_api_sessions.py` coprono retry ed errori. Il quiz con meno domande del richiesto riceve HTTP 422 prima del salvataggio. | Rifiutare un output non garantisce qualità semantica di uno formalmente valido. |
| Refresh, disconnessione, ripresa | Stato e tentativi persistiti nel DB; `test/test_session_interruption.py` e `test/test_api_sessions.py` coprono interruzione e ripresa. | Un arresto brusco fra DB, file e Chroma resta un rischio multi-store (C6 in `ISSUES.md`). |

## 5. Conclusione proporzionata

Il difetto specifico degli ID collidenti è risolto e verificato con più PDF. I controlli aggiunti impediscono anche di riferire come completa un'indicizzazione già parziale e rilevano un file modificato. La completezza formale dei giudizi e i principali errori di flusso hanno regressioni automatiche. La coerenza semantica dei giudizi e la qualità end-to-end dell'AI non sono ancora dimostrate: il run reale esistente valuta un prompt isolato, con tre dispense brevi e un solo modello. Questo documento non considera quelle voci chiuse.

Verifiche eseguite il 12 ottobre 2026: `uv run --extra dev pytest -q` → **358 passed, 1 deselected** (la prova con modello reale è esclusa); `uv run --extra dev python eval/run_eval.py --validate-only` → casi validi; `uv lock --check` e `git diff --check` → esito positivo. Gli SHA-256 degli artefatti modificati sono stati ricalcolati dopo i test; non esiste una checksum precedente con cui confrontarli. Una nuova esecuzione con provider reale non è stata effettuata in questa verifica: le metriche sopra provengono dal risultato datato conservato in `eval/results/`.
