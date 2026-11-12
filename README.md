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
- **Next steps** — three tabs. **Plan**: a ranked "Do next" list (urgent findings, advisor recommendations, record gaps — each with its reason and source quote; Done / Not relevant), plus an AI-written plan built by an *advisor pack*. **Advisors' recommendations**: every recommendation found in your documents (who, when, how firmly), tracked open / done / dismissed, with a "possibly done" hint when a later event or scan matches; add advice given in person. **Checks**: readiness for five decisions (understand response, oncologist visit, second opinion, trial screening, personalised-vaccine feasibility) and a record checklist you fill in. Missing data is **unknown**, never negative; "not done" is recorded separately and still blocks.
- **Advisor packs** (LocalAgents-style) — YAML files in `backend/app/advisor_packs/` (`next_steps`, `visit_prep`, `second_opinion`, `wellbeing`). A pack declares its scopes (which facts it may read), scenarios (one specialist each), guardrails, lead prompt and output sections. Code gathers the facts; specialists and a lead write from them; a validator removes unknown `[R#]` tags, unsafe wording and invented numbers, repairs once, and otherwise falls back to a deterministic plan (also used when the model is down). Plans are marked *stale* when the record changes. Add your own packs under `<data>/advisors/` (higher `version` wins; problems are listed in the UI). A pack may set `allow_general_figures: true` (lifestyle text such as "5 minutes"); clinical packs never may, so any figure not in the facts is rejected. Building a plan takes several minutes on a local model and runs in the background.
- **Case file / Timeline** — editable summary; append-only history of uploads, confirmations and safety alerts.
- **Safety** — code-level red-flag triage before the model (emergencies skip the model) and an output linter after it (stop/skip/replace treatment, dosing, diagnosis claims, outcome promises).
- Every answer is logged in `cc_agent_run` (prompt version, model, retrieved excerpts, safety results).

### Design principles taken from [popvax/yash](https://github.com/popvax/yash)

Explicit evidence tiers (present / negative / not done / unknown — no absence inferred from missing data), explicit gates with every rejection kept, provenance (quote + document + page) on every fact, local computation kept separate from model output, and a vaccine-feasibility gate that names the missing inputs (tumour NGS, matched-normal DNA, tumour RNA, HLA typing). The vaccine workbench itself (variants, HLA, design versions) is the next phase — see [docs/PLAN.md](docs/PLAN.md).

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

## Layout

```
backend/app/services/   safety.py (triage + linter) · agent.py (chat turn) · llm.py (LM Studio) · documents.py · retrieval.py · prompts.py
                        scan_extract.py (verified extraction) · response.py (lesion arithmetic) · requirements.py (checklist + decisions) · readiness.py (gaps + insights)
backend/app/routers/    api.py · record.py
apps/web/src/           App.tsx · pages/{Ask,NextSteps,Progress,CaseFile,Documents,ScanReview,Timeline}.tsx
```

Tables are prefixed `cc_` so the module can move into Loonie as the Health blueprint.
