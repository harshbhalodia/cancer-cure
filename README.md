# Cancer-Cure Companion

A local-first companion that keeps one living **Case File** for a patient — reports, doctor advice,
medicines, diet, routine and mindset — and helps prepare the next course of action with the oncology
team. Everything runs on this computer: LM Studio (local model), SQLite, files on disk.

> Information only. It does not diagnose, prescribe, or recommend changing treatment.

Roadmap and design: [docs/PLAN.md](docs/PLAN.md).

## What it does

- **Today** (the landing screen) — your **next steps, daily plan and how you are doing, on one page**. *Focus now* shows the top three next steps. *My intention* holds your own recovery vision, today's intention and a gratitude line (manifestation, framed as support for how you cope and never as a treatment). A one-minute **check-in** (energy, mood, appetite, pain 0–10, sleep, weight, symptoms; every field optional, blank = unknown) saves as you go; red-flag symptom wording or pain of 8+ shows an alert immediately. The **daily checklist** covers Medicines, Diet, Routine, Mind & manifestation, Movement & rest and People & support, with time-of-day chips, streaks and a 7-day dot row; start from a gentle one-tap set or add your own. **Medicines are found in your documents** (a background `meds` job reads prescriptions and discharge notes; each is verbatim-quoted, dose copied exactly as written, shown as a *suggestion* until you press "I take this", and the app never suggests a dose). **Strategy & ideas** builds an AI strategy for diet, routine, medicines (staying on track), mind and movement from your own plan, check-ins and advisor recommendations (`wellbeing` advisor pack, same validator, never claims that a food or practice treats cancer) plus a library of starter ideas. **Improvements** compares this week with last week for each check-in measure (knowing that for pain lower is better) and for habits kept, with sparklines; it is plain arithmetic over your own entries, not a medical measurement. The chat sees your medicines and recent check-ins, labelled self-reported.
- **Ask** — chat grounded in the case file, documents *and* the structured record below; answers cite `[D<id> p<page>]` and unresolvable citations are removed.
- **The case file is a history, not a single record** — every value (from a report or from you) is stored as a dated, sourced entry and **never overwritten**. The current case file is derived from the history: for each field, the entry with the **latest report date** wins, so uploading an old report can only add to the history and can never replace something newer; an undated entry never beats a dated one. Treatment history, biomarkers, care team and notes are cumulative lists in date order. A **journey** of dated events (biopsy, surgery, radiotherapy, scans…) is built from reports, each with its quoted source line, and an AI-written summary of the whole history (hedging preserved, flagged as out of date when the history changes) sits at the top of the Case file page. When you review a report, the dialog says for every value whether it "becomes current" or is "history only (older than the current value)". Values that existed before history was introduced are kept with an unknown date; set their real dates from the field's History panel.
- **Bulk upload, processed in the background** — drop any number of files (or a whole folder) on any page, or put them in the repo's `uploads/` folder (watched automatically; files are left in place). Uploads return in milliseconds. A persistent single-worker queue then (1) adds each file to the library so it is searchable straight away, and (2) has the local model prepare scan and case-file suggestions. Suggestions wait in the **Inbox** for your review; nothing is applied automatically. The worker steps aside while you chat, a failed file never blocks the rest (retry from the Inbox), and queued work survives a restart.
- **Scanned documents are read automatically** — image-only PDFs, photos of reports and handwritten notes (including Gujarati/Hindi) are transcribed page by page by the local vision model (about 30 s a page) inside the same background queue, then analysed like any other report. Pages are saved as they are read, so an interruption resumes where it left off; blank pages are skipped without calling the model. Transcribed text is flagged **AI-read scan — check the original** in the Documents list and in chat (names, numbers and dates can be misread, especially in handwriting).
- **Documents → Read scan data** — the local model proposes lesion sizes, SUVmax, findings (keeping the report's hedging: "appears", "could be") and the report's own response; **every item must be backed by a verbatim quote and numbers present in the document, or it is discarded and listed as rejected**. You confirm before anything is saved.
- **Progress** — lesion-size chart over time and, per scan, the report's conclusion next to an app-computed size summary (RECIST thresholds against the previous scan; arithmetic is deterministic code, not the model).
- **Vaccine research workbench** (🧬 Vaccine) — a yash-style, auditable pipeline that shortlists which of a tumour's mutations the patient's own immune system could recognise. **It is a research shortlist for the care team, not a vaccine**: a personalised vaccine can only be made and given by a qualified team under an approved trial or pathway, and the app gives no manufacturing, purchasing or dosing information. *Fastest route* (the default tab) is for when time is short: it lists the steps to run in parallel (tumour blocks and blood for whole-exome/RNA sequencing and HLA typing, trial-centre and tumour-board contact, second opinion), shows what the uploaded reports actually say (e.g. the Core report on file is PD-L1 only, with the DNA/RNA panel pending), explains why a negative small gene panel does not rule out vaccine targets, and offers copy-ready drafts for a trial centre, the pathology lab and the oncologist, built only from the records. *Clinical trials* reads a trial's official ClinicalTrials.gov text (only the NCT number or generic search words leave the computer), compares every eligibility line with the documents and the family's answers (supported / to check / not on file / routine), flags what the records cannot show (ECOG, treatment lines with drug names and dates, salvage-surgery opinion, tissue, current labs, the neck-vein clot), lists registry inconsistencies and logistics (e.g. surgery required at the site, no site in India), drafts the enquiry to the study team, keeps an enquiry log, and re-checks the registry for changes. Family-reported facts are labelled unverified until a document backs them; it never decides eligibility. *Treatment options* lists ten options to discuss with the oncologist (surgery, re-irradiation, checkpoint immunotherapy, platinum, cetuximab, taxane, oral metronomic chemotherapy, biomarker-matched treatment, trials, supportive care) with an evidence label, what the records show for each, and questions to ask; it is written by hand from established practice, is deliberately not a ranking, and is not derived from the synthetic cohort. *10K synthetic cohort* runs thousands of made-up tumours shaped like the case (tumour type, FFPE sample, small residual lesion) through the same pipeline with the real predictor as a separate background process (`python -m app.vaccine.cohort run --n 10000`, about 5 minutes after a one-off 2-minute predictor table build): it shows the expected yield, how it depends on mutation count and HLA type, and what a missing tumour RNA, matched normal or an exome-less small panel costs, and it places the patient's real result among similar simulated tumours once loaded. A lookup table of the real predictor is verified against it before any scenario runs. **The 10,000 scenarios run on the CPU predictor and do not use LM Studio; the local model does the judging afterwards** (`python -m app.vaccine.audit`, started from the tab): on simulated tumours without a matched normal it flags candidates that look inherited, and is scored against the planted truth and against a one-line rule (VAF at least 0.40), with the verdict shown plainly; it also writes a cohort memo whose numbers are checked against the facts. It never changes a score. It cannot show that a vaccine works or which treatment is better. *Where you are* shows what the pipeline needs from the patient (tumour sequencing, matched normal, tumour RNA, HLA typing) and the exact questions to ask the oncologist. *Data* takes a pasted mutation table or an annotated VCF plus the HLA type (reference proteins are looked up only on request, sending gene symbols alone). *Candidates* runs the pipeline as a background job: simple substitutions → quality (VAF, depth) → germline (matched normal) → expression (RNA) → reference check (wrong isoform/build rejected) → presentation (8–11-mer peptides covering the mutation, scored against the patient's own HLA alleles by the real **MHCflurry** class-I predictor) → transparent weighted score, evidence tier A/B/C and a diverse selection. Every rejection keeps its reason; every candidate shows its score breakdown and caveats. Runs are **deterministic and replayable**: predictor numbers are stored, and "Verify by replay" rebuilds the selection and must match the result hash exactly. *Review & evals*: the local model acts as a review board (immunology, tumour biology, risks, hand-off) that writes a tumour-board memo from the computed facts only — its opinion never changes a score and the memo is checked for invented numbers/genes/peptides and efficacy claims — and an eval suite (gates vs planted ground truth on a **synthetic** tumour, determinism, replay, order invariance, threshold monotonicity, HLA dependence, published-epitope recovery by the predictor, dossier safety) shows the software behaves as documented. A downloadable markdown/JSON **dossier** is the hand-off to a tumour board or trial centre. Not built: frameshift/indel/splice/fusion/self antigens (need transcript-level translation), class II, mRNA/DNA construct design, and **model fine-tuning** (no real labelled data exists here; training on labels the pipeline invented would be circular). Install the predictor with `pip install mhcflurry` then `mhcflurry-downloads fetch models_class1_presentation`; without it nothing is selected and no substitute score is invented.
- **Watch** (on Today) — log how things are **as many times a day as you like**: energy, mood, appetite, pain, quick symptom chips (neck swelling, breathlessness, chest pain, bleeding, fever, vomiting, trouble swallowing, new lump…), optional vitals (temperature in °C or °F, pulse, oxygen, blood pressure, weight) and a note. Each log is compared with **your own usual numbers** by plain, readable rules (no hidden model), and the answer comes back **immediately** under the form. Alerts have levels — *Emergency*, *Act today*, *Keep an eye on*, *Recovering* — and each lists exactly what to do now (call the emergency number or the team, recheck in N minutes, log again, check the pack) with a "recheck in…" reminder and an "I've done this" button that keeps it quiet until it gets worse. Rules cover symptoms, vitals, pain, weight loss, **medicines** (not ticked today, or not for two days), **diet** (appetite and weight), **routine** (sleep), **mind** (low mood three days; words of despair get an immediate "reach out now" response), and **reports** (an urgent scan item still open after a day). Slow slides are **predicted** with a straight-line trend over the last week ("appetite is heading down… about 1.3/5 within 3 days") before they cross a line, and **recovering signs** (pain easing, appetite/energy/mood improving, fever settled) are called out with a "what helped?" prompt. A sidebar badge, a banner on every page, the page title and optional browser notifications make sure an urgent alert is not missed, and the advisors and chat see the active alerts. Steps only ever say to check, recheck, log again or call, never to change treatment or doses; the thresholds are conservative starting points for your oncologist to review (see "How the alerts are decided" in the Watch & trends tab).
- **Doctor visit** (a tab in Next steps) — a consultation checklist built by code from the latest scan and your journey, in priority order: the urgent finding, the still-active lesion, the lymph node, previous treatment (including "was the planned operation actually carried out?"), and the overall plan (multidisciplinary/tumour-board review, urgency, next scan, treatment objective, comparing against the real earlier records and not only the last comparator). It adds a **Tell the doctor** list pre-filled from your own check-ins and medicines (neck symptoms, pain, appetite, weight change, current medicines), a "don't leave without clarity on" box, and an emergency line. At the visit, tick each question as you ask it, type the doctor's answer under it, and write the advice (one item per line). **Save this visit** adds a dated consultation with every answer to the journey and turns each advice line into a tracked recommendation. "Copy checklist as text" gives a printable version.
- **Next steps** — three tabs. **Plan** opens with **Settle these first**, built by plain code from the latest scan (no model): an unexplained blood-vessel finding (urgent), a lesion that is smaller but still active (high), and agreeing the next treatment plan (high). Each track lists the facts (sizes and SUVs, including a vein clot's size when the report states it), concrete questions to ask the care team, and the quoted source; the items are also tracked as open, *app-suggested* recommendations that say they are questions, not medical orders. Below it: **quick questions** only you can answer (is treatment ongoing, is the neck swollen or painful — saved to today's check-in with a same-day alert if yes, was an old planned operation actually carried out), a **message to the oncologist** built only from confirmed figures, and the ranked **Do next** list. Recommendations are read for what they are: **conditional** advice ("MRI *if* there is suspicion…") is labelled *Only if…* and ranked lower, and **older plans** are labelled *Check if it was done* — a plan is not proof it happened, so you answer Yes / No. **Advisors' recommendations**: every recommendation found in your documents, tracked open / done / dismissed, with a "possibly done" hint when a later event or scan matches; add advice given in person. **Checks**: readiness for five decisions and a record checklist you fill in. Missing data is **unknown**, never negative; "not done" is recorded separately and still blocks.
- **Advisor packs** (LocalAgents-style) — YAML files in `backend/app/advisor_packs/` (`next_steps`, `visit_prep`, `second_opinion`, `wellbeing`). A pack declares its scopes (which facts it may read), scenarios (one specialist each), guardrails, lead prompt and output sections. Code gathers the facts; specialists and a lead write from them; a validator removes unknown `[R#]` tags, unsafe wording and invented numbers, repairs once, and otherwise falls back to a deterministic plan (also used when the model is down). Plans are marked *stale* when the record changes. Add your own packs under `<data>/advisors/` (higher `version` wins; problems are listed in the UI). A pack may set `allow_general_figures: true` (lifestyle text such as "5 minutes"); clinical packs never may, so any figure not in the facts is rejected. Building a plan takes several minutes on a local model and runs in the background.
- **Case file / Timeline** — editable summary; append-only history of uploads, confirmations and safety alerts.
- **Safety** — code-level red-flag triage before the model (emergencies skip the model) and an output linter after it (stop/skip/replace treatment, dosing, diagnosis claims, outcome promises).
- Every answer is logged in `cc_agent_run` (prompt version, model, retrieved excerpts, safety results).

### Design principles taken from [popvax/yash](https://github.com/popvax/yash)

Explicit evidence tiers (present / negative / not done / unknown — no absence inferred from missing data), explicit gates with every rejection kept, provenance (quote + document + page) on every fact, local computation kept separate from model output, and a vaccine-feasibility gate that names the missing inputs (tumour NGS, matched-normal DNA, tumour RNA, HLA typing).

## Patient Action & Research Navigator

- **Patient workspace** in the sidebar selects a patient; **Add a patient** starts an empty case with its own database, uploads, inbox, jobs and research records. **Existing patient** preserves the original case and files in place. Selection reloads the page so old patient responses are not displayed in the new workspace.
- **Today → Follow-ups** keeps questions with an owner, follow-up date, priority, source evidence and change history. Track an existing suggestion or write your own. Move through open, contacted and awaiting reply; resolving requires a recorded answer. This does not acknowledge a medical alert or change treatment. Preview the visit summary before copying or sharing it.
- **Vaccine → Clinical trials** retains registry snapshots, planned endpoints, protocol version, coordinator replies, tissue questions, travel logistics and next follow-up. Turn a question into a Today follow-up. Planned endpoints are not published results. Family-entered ECOG, surgery and autoimmune answers remain unverified; named drugs are not assumed interchangeable, and missing records remain unknown. The study team decides eligibility.
- **Research → Evidence cards** stores public citations and reported endpoints/results, sample size, follow-up, evidence level and limitations. Cards and the comparison profile are manually entered and unverified; this page does not fetch publications or search the web. Disease wording, sarcomatoid differentiation, setting and prior PD-1 are described as resembles/differs/unknown. Missing subtype wording stays unknown. Stage, ECOG, treatment line and biomarkers are not matched; this is not a patient-benefit prediction or a clinical ranking.
- **Vaccine → Ranked targets → Parameter experiment** validates VAF, expression, presentation and selection-count settings before queuing a computational run. **Research → Computational experiment snapshots** saves immutable copies of completed runs, including candidate ranks/scores, caveats and provenance. Compare two snapshots to see parameter changes and added/removed/shared candidates. Controlled comparisons require matching underlying input/reference fingerprints, pipeline version, dataset and predictor; incomplete provenance or changed inputs is labelled non-controlled. Snapshots survive deletion of the source run.

On startup, existing experiment tables are upgraded without deleting snapshots. Older snapshots
without comparison provenance remain non-controlled; the app does not invent missing fingerprints.

**Creating scenarios:** Ranked targets shows a selectable run history. Re-running identical data
and settings creates another execution, not different biology. Enter a hypothesis and use
**Run parameter experiment and save scenario** to retain a new immutable Research snapshot automatically.
Missing mutation/HLA inputs are rejected before queuing; patient data never fall back to synthetic data.
The four editable filters override the viewed run's settings; execution uses the currently loaded data.

**Local AI assistance:** From a completed run, **Draft scenario hypotheses with local AI** queues
LM Studio to draft questions about predefined bounded parameter variations. It cannot invent inputs
or numerical settings; the user reviews/applies a draft and separately approves execution.
In Research, **Review snapshot with local AI** interprets only that immutable snapshot, retains
the model identity and never changes scores. Both jobs persist and show queued/running/failed states.
Outputs are checked for treatment advice and unsupported figures; rejected or unavailable model
responses are errors, not fabricated successful reviews. No web research or clinical validation is performed.

### Private source research notebook (no sequencing required)

In **Research**, open **Add correspondence or a publication excerpt**. Save the relevant passage,
its source type and date (remove signatures, contact details and unnecessary identifiers first).
Correspondence is reported correspondence, not a published result; personal notes are not medical evidence.
A URL is stored only as a citation and is never fetched by this notebook.

Select up to eight sources, ask a question or choose a starter question, and click
**Build source-grounded brief with local AI**. The brief separates reported study requirements,
tentative concerns, evidence notes, unanswered questions and desk-research tasks. Every reported point
selects a numbered passage from a frozen source; the server copies its quotation verbatim rather
than asking the model to reproduce punctuation, spacing or decimal values. An invalid reference, format
or other validation failure gets one explicit correction attempt and full revalidation; persistent errors
still fail rather than accepting approximate citations or unsupported claims.
Unknown sources/passages, unsupported figures,
tentative concerns promoted to findings and detected procedural content cause an explicit failed job.
These checks do **not** establish semantic correctness or clinical validity; review the original source.
If a brief fails, **Retry brief #... with saved sources** reuses its original question and frozen excerpts;
there is no need to re-enter them. The Inbox retry action also works for the same job.

The notebook sends only your question and selected excerpts to a loopback LM Studio endpoint.
It does not automatically read the patient record, search the internet, or use model memory as medical evidence.
Source text is limited to 12,000 characters per entry and 36,000 per brief; oversized requests fail without
silently truncating evidence. Sources are append-only; save dated corrections as new sources.
Briefs retain frozen copies of their sources, model identity and an input fingerprint; the latest twenty
are shown, with progress and errors. Review before copying a brief; sharing is never automatic.

### Reviewed local research loops

Select local notebook sources and enter a research question, then choose **Start reviewed research loop**.
One cycle creates a cited brief and asks the local model for a separate critical reading of every
extracted point, source-linked evidence gaps and a proposed next question. The critique is a second pass
by the same model, **not independent verification or clinical validation**.

Review the saved cycle and original excerpts before choosing **Approve next question and run one cycle**.
Each approval authorises exactly one further cycle; duplicate or stale approvals are rejected.
There are at most three cycles per loop. The loop stops on flagged interpretations, a repeated question,
no additional cited source passages, no next question, or a gap requiring new sources. Add reviewed
excerpts and start a new loop when the evidence base needs to change. Re-reading unchanged material
cannot establish new scientific evidence, a treatment benefit or a cure.

Loops freeze their sources, retain cycle results and model identities, and remain patient-isolated.
Failed cycles can be retried with their original inputs; **Close loop** prevents further approvals
(a running cycle may finish; a queued cycle is explicitly skipped). Duplicate loops with identical questions and sources are rejected.
The notebook shows the latest ten loops, including their stop reasons and source-coverage counts.
These counts are not efficacy or clinical-progress measures.

Only the selected local excerpts are used. There is no web discovery, implicit access to the case file,
automatic computational execution, laboratory work, treatment change, self-modifying code or model training.
Generated briefs and critiques never become new evidence sources. Source attribution/format and safety
failures get at most one correction per brief or critique and are fully revalidated; persistent failures
remain explicit failed jobs, without automatically starting another cycle.

This supports reading and computational research **not** in-house vaccine development. A study-centre's
tissue requirements cannot be bypassed with software. Possible treatment-related necrosis is not a confirmed
pathology finding, and omitted variant wording is not an eligibility decision. The neoantigen pipeline is
not a TMV vaccine model. This notebook provides no laboratory, tissue-handling, manufacturing, dosing or
administration protocol and cannot replace oncology care, qualified laboratory work or clinical-trial oversight.

Tumour-derived TMV vaccines and sequencing-based neoantigen peptide shortlists are different research platforms. Computational scores, synthetic cohorts and published group outcomes do not demonstrate personal benefit, establish eligibility, or provide a vaccine manufacturing or treatment protocol.

> The requirements checklist in `backend/app/services/requirements.py` and the red-flag rules in `services/safety.py` are conservative starting points. Have the treating oncologist review and edit them.

## Run

Requirements: Python 3.11+, Node 20+, LM Studio's server on `http://localhost:1234` with the model loaded.

```powershell
.\scripts\setup.ps1   # once
.\scripts\start.ps1   # API on :8100 (new window) + web on http://localhost:5174
```

Settings are `CC_`-prefixed environment variables or `backend/.env`
(`CC_LM_MODEL`, `CC_LM_ENDPOINT`, `CC_LM_TIMEOUT_S`, `CC_EMERGENCY_NUMBER`, `CC_DATA_DIR`, `CC_INBOX_DIR`, `CC_WATCH_INTERVAL_S`, `CC_WORKER_ENABLED`).

## Test

```powershell
cd backend; .\.venv\Scripts\python.exe -m pytest -q
```

## Privacy

Patient data lives in `backend/data/` (database + uploads). `backend/data/`, `ref/`, `*.db` and `.env*`
are git-ignored — never commit real records. Tests use synthetic text only.

The original patient uses `CC_DATA_DIR` and `CC_INBOX_DIR` (the repo's `uploads/` by default).
Added patients use `<CC_DATA_DIR>\patients\<workspace-id>\` and their own `inbox\` underneath it.
Files dropped in the original inbox still belong to **Existing patient**, not the selected sidebar patient;
use browser upload with the intended patient selected, or its dedicated inbox.
Stop the app before backing up the entire data directory and original inbox.

This is a private local tool, **not an authenticated shared clinic service**. Workspace selection
separates records but is not access control or encryption. Keep it on trusted localhost and secure
the computer and backups. Public registry/reference requests are explicit; research cards do not
send patient information to external search services.

## Layout

```
backend/app/services/   safety.py (triage + linter) · agent.py (chat turn) · llm.py (LM Studio) · documents.py · retrieval.py · prompts.py
                        scan_extract.py (verified extraction) · response.py (lesion arithmetic) · requirements.py (checklist + decisions) · readiness.py (gaps + insights)
backend/app/routers/    api.py · record.py
apps/web/src/           App.tsx · pages/{Ask,NextSteps,Progress,CaseFile,Documents,ScanReview,Timeline}.tsx
```

Tables are prefixed `cc_` so the module can move into Loonie as the Health blueprint.
