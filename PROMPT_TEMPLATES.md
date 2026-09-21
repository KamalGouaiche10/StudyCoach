# Prompt Templates — SDD con Copilot

*Companion operativo alla Lezione 8. Quattro template da copiare in Copilot Chat durante l'esercitazione.*

---

## Come usare questo file

Quattro template, da usare **in ordine**:

1. `AGENTS.md` — una volta per progetto (scegli greenfield **o** brownfield)
2. `PLANNING.md` — una volta per feature
3. `TASKS.md` — una volta per feature, dopo aver approvato PLANNING

Per ciascuno:
- **Sostituisci** i segnaposti `<...>` con contenuto specifico
- **Copia** il prompt intero in Copilot Chat (sidebar)
- **Leggi** l'output, modificalo dove serve, salva nel repo, committa

**Regola che vale per tutti i template:** non accettare il primo output così com'è. L'AI risponde sempre qualcosa di plausibile, non sempre qualcosa di corretto per il tuo caso.

---

## Template 1 · AGENTS.md — greenfield

**Quando usarlo:** stai iniziando un progetto da zero, la cartella è vuota o contiene solo un `README.md`.

**Dove incollarlo:** Copilot Chat, senza `@workspace` (non c'è ancora nulla da indicizzare).

**Cosa aspettarti:** un draft basato su best practice generali, che tu dovrai poi adattare ai vincoli reali del tuo progetto.

```
Aiutami a scrivere AGENTS.md per un nuovo progetto.

Descrizione del progetto:
<una frase: cosa fa, per chi>

Stack tecnologico:
- Linguaggio e versione: <es. Python 3.11+>
- Librerie principali: <es. pytest, stdlib only>
- Runtime/piattaforma: <es. CLI locale, niente server>

Vincoli di dominio:
<eventuali vincoli specifici: mono-utente, offline, limiti di
memoria, compatibilità richiesta, ecc. Se non ce ne sono, scrivi
"nessuno">

Regole della conversazione:
1. Se ti manca un'informazione essenziale, FAI DOMANDE prima di
   scrivere. Non inventare.
2. Proponi 2-3 opzioni concrete quando devi scegliere una
   convenzione (es. naming, testing framework). Motiva la tua
   proposta in una riga.
3. Se indico un default, rispettalo senza discuterlo.
4. Non aggiungere sezioni non richieste (es. "Deployment",
   "CI/CD") se non ho menzionato quei temi.

Vincoli sul file finale:
- Massimo 40 righe totali
- Sezioni: Overview, Stack, Convenzioni, Testing, Evitare
- Solo cose azionabili, niente filosofia
- Nessun esempio di codice (non è un README)

Non scrivere il file finché non te lo chiedo. Iniziamo con la
prima domanda che ti serve per chiarire il brief.
```

**Revisione dell'output:**
- Hai riconosciuto come "tue" le convenzioni proposte, o ci sono cose assunte dall'AI che non rispecchiano le tue preferenze?
- Mancano vincoli di dominio che sai valere per il tuo caso?
- Ci sono cose "generiche" che potresti togliere senza perderci nulla?

---

## Template 2 · AGENTS.md — brownfield

**Quando usarlo:** la codebase esiste già (come nel caso di `todo_app/`).

**Dove incollarlo:** Copilot Chat, **con `@workspace`** (l'AI deve leggere il codice).

**Cosa aspettarti:** una descrizione delle convenzioni osservate nel codice + una sezione di debito tecnico. Attenzione: l'AI è brava a leggere ma tende a "armonizzare" le incoerenze. Verifica a campione.

```
@workspace

Analizza questa codebase e proponimi un AGENTS.md.

Regola fondamentale:
NON prescrivere buone pratiche. DESCRIVI ciò che c'è nel codice.

In particolare:
1. Leggi i file principali e osserva: stack realmente usato, stile
   di naming effettivo, pattern di testing presenti, modo in cui
   sono strutturati i moduli.
2. Se trovi convenzioni seguite in modo coerente, riportale in
   "Convenzioni".
3. Se trovi INCOERENZE (es. naming misto, alcuni moduli con test
   altri no), NON sceglierne una. Mettile in una sezione separata
   "Debito tecnico rilevato" con esempi specifici (file e riga).
4. Se una convenzione non è verificabile dal codice, NON inventarla.
   Scrivi "[da chiarire con il team]".

Vincoli sul file finale:
- Massimo 50 righe totali (incluso il debito tecnico)
- Sezioni: Overview, Stack, Convenzioni, Testing, Evitare, Debito
  tecnico rilevato
- Nella sezione "Evitare", metti solo red flag che hai visto
  ripetersi, non best practice generali

Prima di scrivere, se hai bisogno di leggere file specifici oltre
a quelli principali, dimmelo.
```

**Revisione dell'output:**
- Prendi 2-3 affermazioni del file ("usa snake_case dappertutto", "test solo per il modulo X"): sono vere? Apri il codice e verifica. Se queste sono corrette, il resto probabilmente lo è.
- La sezione "Debito tecnico rilevato": sono veri difetti o sono scelte intenzionali che l'AI non poteva capire? Rimuovi i falsi positivi.
- Il file è **descrittivo** o ha iniziato a **prescrivere**? Se vedi frasi tipo "i test dovrebbero usare fixture", è slittato verso il prescrittivo. Riporta al descrittivo.

---

## Template 3 · PLANNING.md

**Quando usarlo:** hai `AGENTS.md` committato e vuoi iniziare una feature. Usalo **una volta per feature**.

**Dove incollarlo:** Copilot Chat con `@workspace`.

**Cosa aspettarti:** un piano di alto livello con obiettivo, approccio, rischi, non-obiettivi, criteri di accettazione. Niente dettagli implementativi — quelli arrivano con TASKS.

```
@workspace

Ho AGENTS.md nel repo. Voglio scrivere PLANNING.md per una feature.

Feature da pianificare:
<descrizione in 1-3 frasi di cosa vuoi aggiungere o modificare>

Prima di proporre il piano:
1. Leggi AGENTS.md e rispettalo.
2. Leggi i file esistenti che saranno coinvolti da questa modifica.
3. Se la feature è ambigua, FAI DOMANDE prima di scrivere il piano.
   Esempi di ambiguità da sciogliere: comportamento sui casi limite,
   integrazione con funzionalità esistenti, retrocompatibilità.
4. Proponi il piano solo dopo che abbiamo chiarito le ambiguità.

Struttura di PLANNING.md (rispetta esattamente queste sezioni):
- Obiettivo (1-2 frasi — cosa fa la feature dal punto di vista
  dell'utente)
- Approccio (3-5 righe — come la implementeremo, scelte principali)
- Rischi e trade-off (2-4 bullet — cosa potrebbe rompersi, quali
  compromessi accettiamo)
- Non-obiettivi (2-3 bullet — cose che NON copriamo in questa
  iterazione ma potrebbero sembrare implicite)
- Criteri di accettazione (3-5 bullet verificabili — come sappiamo
  che la feature è fatta)

Vincoli:
- Massimo 40 righe totali
- Niente codice, niente signature di funzioni, niente nomi di file
  (quelli stanno in TASKS)
- I criteri di accettazione devono essere VERIFICABILI (non "deve
  essere veloce", ma "deve rispondere in <100ms" o "deve passare
  il test X")

Iniziamo dalle domande di chiarimento se ne hai.
```

**Revisione dell'output:**
- I criteri di accettazione sono **verificabili**? Se leggi "l'interfaccia deve essere intuitiva", non lo è. Riscrivi o rimuovi.
- I **non-obiettivi** sono espliciti? Questa è la sezione che l'AI tende a trascurare ma che protegge dallo scope creep.
- Il piano rispetta davvero `AGENTS.md`, o ha introdotto pattern/dipendenze che contraddicono le convenzioni?
- Stai ancora parlando di **cosa** (utente) o sei scivolato in **come** (implementazione)? Se vedi nomi di classi o funzioni, l'AI è andata troppo in basso.

---

## Template 4 · TASKS.md

**Quando usarlo:** hai PLANNING.md approvato. Questo template traduce il piano in passi atomici.

**Dove incollarlo:** Copilot Chat con `@workspace`.

**Cosa aspettarti:** una lista numerata di task, ciascuno risolvibile in un pass di Copilot (~30 righe di codice).

```
@workspace

Ho AGENTS.md e PLANNING.md nel repo. Ora voglio TASKS.md.

Obiettivo:
Spezzare il piano in task atomici, uno alla volta implementabili da
Copilot (Edit mode o Agent mode) in un singolo pass.

Vincoli sui task:
1. Ogni task deve essere risolvibile in ~30 righe di codice o meno.
   Se un task richiederebbe più codice, SPEZZALO in due.
2. Ogni task deve produrre un commit indipendente (niente
   dipendenze circolari: T2 può dipendere da T1, ma T1 non deve
   dipendere da T2).
3. Ogni task deve indicare:
   - Cosa fa (1 riga)
   - Quali file tocca
   - Se richiede test, e di che tipo
4. Se due task sono indipendenti tra loro, segnalalo con [P] (può
   essere parallelizzato).
5. Il PRIMO task deve produrre qualcosa di eseguibile (anche solo
   un modulo vuoto importabile). Serve a verificare lo scaffold
   prima di metterci dentro logica.

Formato del file:
- Titolo del task (T1, T2, …)
- Checkbox `- [ ]` davanti
- Descrizione 1 riga
- Sotto, lista puntata con: file toccati, test richiesti,
  dipendenze da altri task

Vincoli sul file:
- Massimo 10 task totali. Se ne servono di più, PLANNING era
  troppo grande: segnalamelo invece di produrre una lista enorme.
- Ogni task deve essere leggibile in 2-3 righe totali.

Prima di scrivere i task, se vedi ambiguità nel piano, dimmelo.
```

**Revisione dell'output:**
- Leggi i task dal primo all'ultimo: riesci a immaginare come li implementerai?
- Il primo task produce qualcosa di installabile/eseguibile? Se parte già con logica di business, chiedi di mettere prima uno scaffold.
- Ci sono task troppo grandi? Un task che tocca 3 file e scrive test di integrazione è probabilmente 2-3 task.
- Le dipendenze sono corrette? Se T5 importa qualcosa definito in T6, è un errore di ordinamento.
- I task con `[P]` sono davvero indipendenti, o condividono qualche stato implicito?

---

## Dopo TASKS: il ciclo di implementazione

Non è un template — è il pattern ricorrente che userai per ogni task.

Per ogni task, apri **Edit mode** (o Agent mode per task semplici) e scrivi:

```
Implementa <T1> di TASKS.md.
Rispetta AGENTS.md.
Non toccare altri task.
Spunta <T1> in TASKS.md quando hai finito.
```

Poi:
1. **Leggi il diff** che Copilot propone
2. **Accetta** se rispetta AGENTS e PLANNING
3. **Esegui i test** se il task li prevedeva
4. **Commit** con messaggio che referenzia il task (`T1: setup progetto`)
5. **Prossimo task**

Mai implementare due task nello stesso pass. Mai dire "implementa tutta la feature".

---

## Tre cose da ricordare per tutti i template

1. **"Se ti manca info, fai domande — non inventare"** compare in tutti e quattro. È la frase che separa prompt SDD dai prompt vibe coding. L'AI ha un bias fortissimo verso il generare output anche con input incompleto. Questo vincolo esplicito lo contrasta.

2. **Il vincolo di lunghezza** (40 righe, 50 righe, 10 task) non è estetica. Un AGENTS.md di 200 righe viene ignorato dall'AI. Un TASKS.md con 30 task non verrà mai completato. Se l'output sfora, chiedi esplicitamente di accorciare.

3. **Un approval gate tra ogni fase.** Non passare a PLANNING senza aver approvato AGENTS. Non passare a TASKS senza aver approvato PLANNING. Non implementare senza aver approvato TASKS. Ogni approvazione è **un commit separato**.
