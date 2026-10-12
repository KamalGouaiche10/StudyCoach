# Mappa della migrazione frontend

L'interfaccia viene resa da FastAPI con template Jinja2, HTML e CSS. La logica applicativa è Python e riusa gli stessi servizi e gli endpoint API. Non servono Node.js, npm, React o TypeScript.

| Vista | URL browser | Operazioni Python/API riusate |
| --- | --- | --- |
| Accesso e registrazione | `/web/login` | `backend.api.auth` |
| Libreria esami | `/web/exams` | `backend.api.exams`, `frontend_extras.rename_exam` |
| Dettaglio esame e PDF | `/web/exams/{id}` | ingestione, verifica, reindicizzazione, selezione, appunti PDF, eliminazione fonti |
| Sessione guidata | `/web/study/{id}` | quiz, selezione adattiva, tutor a due risposte, contestazione, report |
| Dubbi socratici | `/web/chat/{id}` e `/web/chat/{id}/history` | `start_doubt`, `answer_doubt`; chat separate in `doubt_threads`, messaggi in `doubt_conversations` |
| Storico e report | `/web/history/{id}` | dettaglio, ripresa, appunti, report PDF, chiusura, eliminazione |

Gli endpoint JSON originali restano disponibili sotto `/auth`, `/exams` e `/sessions`. La nuova UI usa gli stessi moduli Python e il cookie HttpOnly `sc_token`. La root `/` reindirizza all'accesso o alla libreria; `/docs` espone i contratti API.

La selezione delle fonti viene passata alla verifica, alla generazione del quiz e agli appunti PDF. Le conversazioni dei dubbi, incluse le risposte, sono conservate nel database. I form browser controllano l'origine delle richieste POST.

La sessione apre automaticamente la prima domanda dopo la generazione del quiz e chiude il report dopo l'ultima risposta. Mostra avanzamento, media, risposte date, guida, valutazione e contestazione. Lo storico consente di riprendere o eliminare le sessioni interrotte e mostra gli appunti formattati nella stessa pagina. Il caricamento multiplo segnala separatamente i PDF riusciti e quelli non utilizzabili.

La generazione degli appunti PDF mostra sotto il pulsante la fonte corrente e la parte in fase di generazione o verifica, poi offre il download. Il browser riceve eventi di avanzamento dalla stessa rotta FastAPI; senza JavaScript resta disponibile il download diretto. La verifica LLM usa un agente JSON separato e non pubblica appunti quando la risposta di controllo è vuota o non valida. Un limite temporaneo del provider configurato viene segnalato con il tempo di attesa quando disponibile.
