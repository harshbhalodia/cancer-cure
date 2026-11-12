# Cancer-Cure Companion — Plan of Action

A local-first companion that keeps one living **Case File** for a patient: every report, doctor
advisory, medicine, meal, routine and mindset entry is captured on a timeline, so an AI agent can
show what is improving and prepare the **next best course of action** for the oncologist
conversation — until the patient is cured. It never replaces the care team.

Built stand-alone now; designed to drop into Loonie as the **Health** blueprint later.

## 1. Principles

1. **Case File is the memory.** Facts live in SQLite, not in chat history. The LLM gets a freshly
   built context pack every turn, so context survives restarts, model swaps and years of use.
2. **Everything has provenance.** Each fact links to a source document/page/date or a user entry,
   and is labelled `confirmed` (user-reviewed) or `extracted` (AI-proposed).
3. **AI proposes, human confirms.** Extracted lab values, medicines and advice go to a review
   queue before they affect trends or answers.
4. **Deterministic first.** Trends, adherence, due dates, red-flag rules and unit conversion are
   plain code. The LLM explains, summarises and drafts questions.
5. **Safety is code, not just prompt.** Red-flag triage runs before the LLM and an output linter
   runs after it (see §6).
6. **Local by default.** LM Studio + SQLite + files on disk. Nothing leaves the machine; any web
   evidence lookup is opt-in and sends only de-identified queries.

## 2. Reuse from Loonie (`lifeos`)

| Need | Loonie asset to copy/adapt |
| --- | --- |
| Stack | FastAPI + SQLAlchemy + Alembic + SQLite, React 19 + Vite + TS, hand-written CSS, recharts |
| Per-user data folder | `config.user_dir` / `user_db_path` (one folder = one backup unit) |
| AI adapter | `services/ai_provider.py` (reasoning-vs-message parsing, timeouts, lock) |
| Agent loop + memory | `services/guru_*`, `guru_memory.py`, `guru_tools.py` |
| Upload + parse | `statement_parsing.py`, `statement_store.py` (pypdf/pypdfium2) |
| Persona tests | `backend/guru_testkit/personas.py` → synthetic patients |
| Scripts | `scripts/setup.ps1`, `start.ps1` |
| Module system | `blueprints/<id>/` → this app is one blueprint from day 1 |

Layout (so migrating into Loonie is a copy, not a rewrite): backend tables prefixed `cc_`, one
router package `routers/cancer_cure/`, frontend under `apps/web/src/blueprints/cancer-cure/`.

## 3. Local model (LM Studio)

Verified: `POST http://localhost:1234/api/v1/chat` returns `output: [{type:"reasoning"}, {type:"message"}]`
plus `response_id`. Rules for the adapter:

- Show/store **only** the `message` item; keep `reasoning` out of the UI and DB.
- Never rely on `response_id` chaining for memory — rebuild context from the Case File each turn.
- Roles: `qwen/qwen3.6-35b-a3b` for reasoning/chat/extraction; a small model (e.g. `qwen/qwen3-1.7b`)
  for intent routing; an embedding model for document search (optional; start with SQLite FTS5).
- Extraction uses JSON-only output + schema validation + one repair retry (`json-repair`).
- Scanned PDFs/images need OCR or a vision-capable model — check which installed model supports it.

## 4. Modules

| Module | Captures | Shows |
| --- | --- | --- |
| **Case File** | diagnosis, stage, histology, biomarkers/mutations, HLA, care team, allergies, goals | one-page summary, version history |
| **Reports** | pathology, labs, imaging, genomics (Caris/Guardant style), discharge notes | extracted values → trend charts, "what changed since last report" |
| **Advisories** | doctor/second-opinion advice (typed, uploaded, or voice-transcribed), date, source | action items with owner/due/status; conflicts between advisors flagged |
| **Medicines** | regimen, cycles, doses as prescribed, adherence, side effects | schedule, missed doses, side-effect trends, interaction check *for pharmacist review* |
| **Diet** | meals, hydration, weight, supplements, appetite | nutrition summary, weight trend, dietitian-constraint checklist |
| **Routine** | sleep, activity, appointments, rest, pain, energy | weekly consistency, correlation with symptoms (labelled correlation, not cause) |
| **Mindset (Manifestation)** | daily intention, gratitude, visualisation, mood | streaks, mood vs. symptoms; framed as support, never as treatment |
| **Progress** | all of the above | Improvement view: biomarker trend, symptoms, weight, function, adherence |
| **Next Actions** | agent-generated | questions for the oncologist, tests due, trials to discuss, visit-prep PDF |
| **Vaccine Workbench** | sequencing + HLA | see §7 |

## 5. Data model (SQLite, `cc_` prefix)

`cc_case` · `cc_person` (patient, caregivers, clinicians) · `cc_document` (file hash, type, date,
source, ocr_text, status) · `cc_document_chunk` (FTS5) · `cc_observation` (code, value, unit,
ref range, date, source_doc, page, status) · `cc_medication` / `cc_med_event` (taken/missed/side effect)
· `cc_meal` · `cc_routine_entry` · `cc_mindset_entry` · `cc_symptom` · `cc_advisory` /
`cc_action_item` · `cc_event` (unified timeline, append-only) · `cc_summary` (rolling case summary
per period) · `cc_chat_message` · `cc_agent_run` (tool calls, prompt version, model — audit) ·
`cc_variant` / `cc_hla` / `cc_candidate` (vaccine workbench).

`cc_event` is the spine: every write also appends an event, so "track every moment" is one query.

## 6. AI agent design

**Per-turn pipeline**

1. *Triage (code):* red-flag rules over the message and latest check-in (fever on chemo, uncontrolled
   bleeding, chest pain, new neuro deficit, suicidal thoughts, severe dehydration…) → show urgent-care
   guidance first and notify the caregiver contact. The thresholds come from the patient's oncology
   team instructions when entered; otherwise conservative defaults.
2. *Route:* small model/rules → intent (question, upload, check-in, plan, vaccine).
3. *Context pack (token-budgeted):* case summary → active regimen → last N observations & trends →
   open action items → relevant document chunks (FTS5/embeddings) → recent timeline.
4. *Tools:* `get_trend`, `search_documents`, `list_open_actions`, `add_observation` (draft),
   `draft_visit_questions`, `search_pubmed` / `search_clinicaltrials` (opt-in). Validate parameters;
   report only tool results that actually succeeded.
5. *Answer* in the structured format below.
6. *Output linter (code + second LLM pass):* blocks dosing, "stop/skip/change treatment", diagnosis
   claims, unsupported citations (every citation must resolve to a stored source or tool result).
7. *Log* to `cc_agent_run`; roll the case summary forward nightly.

**Answer format:** Plain-language answer → What your records show (with source + date) →
Established vs. emerging evidence → What is uncertain / missing → Questions for your oncologist →
Suggested next step (always "discuss with…", never an order).

**Improvements over the SOP provided** (keep all its safety rules; add):

- Patient context and memory (the SOP is stateless) and a *role* switch: patient / caregiver / clinician tone and depth.
- *Ask, don't assume*: list missing inputs (stage, line of therapy, last labs) before answering.
- Deterministic red-flag triage and the output linter above.
- Conflict handling: when advisors/reports disagree, show both with dates and generate a question, never pick a side.
- Evidence labels (`guideline` / `trial` / `case report` / `preclinical`) and recency; no statistic without a stored source.
- Emotional support behaviour: acknowledge, don't over-reassure, never promise cure/prognosis.
- Review queue for extracted data; prompt versioning; eval suite (§9).

## 7. Vaccine Workbench (inspired by `popvax/yash`)

Reality check: a personalised mRNA vaccine needs tumour + matched-normal sequencing, HLA typing, a
validated pipeline, GMP manufacturing, regulatory approval and a clinical team. The app does **not**
produce something to be administered. It does the parts software can responsibly do:

1. **Ingest** genomic reports/VCF/MAF (tumour profiling, liquid biopsy) and HLA type → structured variants.
2. **Dossier**: per-variant evidence table (gene, change, VAF, expression if known, normal-DNA check,
   known driver status) — mirrors Yash's *antigen review* and *provenance* approach.
3. **Candidate ranking (research mode):** optional local pipeline (pVACtools / MHCflurry / NetMHCpan)
   run as an external, versioned job; results stored with tool versions and inputs so they are
   reproducible (`verify` / `reproduce` / `compare` ideas from the Yash repo).
4. **Design versions:** Design #1, #2… compared side by side, as Yash does, with rationale.
5. **Course of action:** match to open personalised-vaccine / neoantigen trials (ClinicalTrials.gov),
   and a one-click *dossier for the oncologist / trial team*. Every screen carries "research
   only — not a medical product".

Defer this until Phases 1–3 are validated; it needs real sequencing data and domain-expert review.

## 8. User experience

- **Today** screen: a 60-second check-in (energy, pain, nausea, appetite, mood, sleep — big tap
  targets), tick today's medicines, log a meal by photo/voice/text, one intention line. Streaks are
  gentle; no guilt copy.
- **Chat-first, drop anywhere:** drag a PDF/photo onto any screen → it lands in the **Inbox**,
  is classified, extracted, and shows "3 values need your review".
- **Timeline:** single scrollable story of the journey with filters; milestones (scan, cycle, result).
- **Progress:** plain trend charts with ranges and neutral language ("CA 19-9 down 38% since Mar")
  and a "what changed" card; no single magic score that could mislead.
- **Visit mode:** *Prepare* (summary + top questions + changes since last visit as PDF) and
  *Capture* (record/typed notes → advisory + action items).
- **Caregiver view:** read-only share/export, reminders, escalation contact.
- Calm design, large text option, dark mode, works offline, keyboard accessible, plain-language
  explanations of every term on tap.
- Onboarding: 5-minute guided Case File (upload a report → auto-fill → confirm).

## 9. Validation (independent of Loonie)

- Synthetic patients only in the repo (adapt `guru_testkit/personas.py`); real data stays in the
  git-ignored `data/` folder.
- Evals: extraction accuracy on sample reports, citation-resolves check, red-flag recall (must be
  ~100% on a scripted set), refusal tests (dosing / stop-chemo / diagnose), context-recall after
  restart, regression tests per prompt version.
- Clinician review of the SOP, red-flag list, and visit-prep output before relying on them.

## 10. Phases

| Phase | Outcome | Done when |
| --- | --- | --- |
| **0 Skeleton** (week 1) | repo, FastAPI + React shell, LM Studio adapter, Case File, chat with memory, safety triage + linter | restart app, ask "what's my diagnosis & last labs?" → correct, sourced answer |
| **1 Reports & Advisories** | upload, OCR/text extraction, FTS search, review queue, observations & trend charts, advisory + action items | a real report becomes confirmed trends in < 5 min |
| **2 Trackers** | Today check-in, medicines, diet, routine, mindset, unified timeline | a week of daily use takes < 2 min/day |
| **3 Progress & Next Actions** | improvement dashboard, what-changed, visit-prep PDF, reminders | oncologist visit prep generated from data alone |
| **4 Evidence** | opt-in PubMed / ClinicalTrials.gov / guideline retrieval with citations | every citation verifiable |
| **5 Vaccine Workbench** | variants, HLA, dossier, versioned designs, trial matching | reproducible dossier from sample data |
| **6 Loonie integration** | move into `blueprints/cancer-cure` as Loonie Health | module registers with no code rewrite |

## 11. Security & privacy

Medical data is highly sensitive: git-ignore `data/`; per-user folder; local PIN/password; encrypt
uploads and DB at rest (SQLCipher or file-level encryption; BitLocker as baseline); encrypted
backups; audit log; export/delete-all; no telemetry (drop Loonie's Sentry); no cloud sync unless
explicitly enabled.

## 12. Decisions to confirm

Answered so far: first users are patient + caregiver (role switch in the UI); seed case is a
tongue-cancer patient (real report kept locally in git-ignored `ref/`); Phase 0 and the first part of
Phase 1 are built (structured record, verified scan extraction, lesion calculator, readiness/gap engine — see README).
Next: pathology and NGS/HLA report parsers (so the vaccine gate can be satisfied from documents), lab trends,
then the Vaccine Workbench.

1. Cancer-specific red-flag thresholds: replace the generic defaults in `services/safety.py` with the oncology team's instructions.
2. Which installed model is vision-capable for scanned reports, or install Tesseract OCR (next: Phase 1).
3. Single-user local PIN now, multi-user later — OK?
4. Move from `create_all` to Alembic migrations when Phase 1 adds tables (matches Loonie).
