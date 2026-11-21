# RxD · proof of concept

RxD helps a clinician choose a **kidney-safe dose**. The clinician records a patient's intake, which goes into a local knowledge store (RAG). They then chat with an assistant about the selected patient. When they name a drug, a **rules engine** decides the dose from FDA label rules and a **small local model** explains it, citing only the passages it retrieved.

> **Prototype · synthetic data · not for clinical use.**

Scope: a proof of concept that runs on one laptop. One FastAPI service (REST API + RAG store), one simple web screen that calls it, no cloud, no API keys.

---

## 1. Run it

Python 3.11+. Ollama is optional: without it the app still answers from the rules and shows the saved record.

```bash
./scripts/start.sh                    # sets up, seeds 30 synthetic patients, runs on http://localhost:8000
```

| Option | Effect |
|---|---|
| `--models` | pull the two Ollama models (needs Ollama: `brew install ollama` or https://ollama.com/download) |
| `--test` | run the tests first |
| `--port 9000` | another port |
| `--reset` | delete `storage/` (database, vectors, uploads) before seeding |
| `--setup-only` / `--no-reload` | set up and exit / run without auto-reload |

API docs: http://localhost:8000/docs. Tests: `make test` (372 tests, no Ollama needed). Evaluation: `make eval`.

**Accounts** (the sign-in page has buttons that fill them in; passwords live in `.env`):

| User | Role | Can |
|---|---|---|
| `dr.evans` | clinician | add patients, save intakes, chat, accept/edit/reject, attach notes |
| `rph.aniket` | pharmacist | chat, attach notes, view rules and audit |
| `admin.sanoj` | admin | view rules and audit, reindex |

**The screen:** pick a patient (or **➕ New patient**), fill the intake form (only the name is required), and chat. The chat knows which patient is selected, so you never type their name. Name a drug (for example "Check metformin") and you get a verdict card: Continue, Adjust dose, Caution, Avoid, or Need more information.

**Demo:** open Maria Lopez and click *Check metformin* (Avoid) and *Check gabapentin* (200 mg once daily). Ask "What medications is she on?" without naming her. Add a new patient (male, 50, 80 kg, creatinine 1.0) and check famotidine (Continue, 20 mg twice daily).

---

## 2. System design

### 2.1 Context

```
 Browser (one screen)                       Laptop
┌────────────────────┐   REST + cookie   ┌────────────────────────────────────────┐
│ patient picker     │ ────────────────▶ │ FastAPI service (app/)                 │
│ intake form        │                   │   controllers → models (services)      │
│ chat + verdict card│ ◀──────────────── │   SQLite   Chroma   rules engine       │
└────────────────────┘                   └──────────────┬─────────────────────────┘
                                                        │ HTTP (localhost)
                                                  ┌─────▼──────┐
                                                  │  Ollama    │  qwen2.5:1.5b (chat)
                                                  │            │  nomic-embed-text (vectors)
                                                  └────────────┘
```

### 2.2 Principles

1. **The rules engine decides the dose; the model only explains it.** The guardrail overwrites any action or dose the model returns with the rule's values, and replaces the model's explanation with the rule's if they disagree.
2. **Every citation was retrieved.** Citations that were not in the retrieved set are dropped.
3. **The app answers even if the model is down.** Dosing falls back to the rule's own text; chat falls back to a summary of the saved record.
4. **Synthetic data only.** A banner is shown on every page.
5. **Patient isolation.** Retrieval is always filtered by the selected patient's id.

### 2.3 How a chat message flows

```
POST /api/v1/chat {patient_id, message, history}
   │
   ├─ no saved intake for this patient ────────────▶ "Fill in the intake form first."
   │
   ├─ message names a supported drug ──▶ DOSING PIPELINE
   │     1. recalculate kidney values (eGFR, CrCl, stage, flags) from the latest intake
   │     2. router: find the drug, parse a stated regimen, pick a persona
   │     3. retrieve: ALL label chunks for the drug + top patient chunks (hybrid search)
   │     4. rules engine: data-quality checks, then the label rule → action, dose, citations
   │     5. model writes the explanation as JSON (Ollama structured output)
   │     6. guardrail: rule overrides model; drop unretrieved citations; set status
   │     7. fallback if the model is down or returns bad JSON twice
   │     8. save suggestion + audit event; clinician accepts, edits or rejects
   │
   ├─ message asks about dose but names no drug ───▶ "Name one of the six drugs."
   │
   └─ anything else ──▶ RECORD Q&A
         retrieve the selected patient's chunks → model answers only from them
         (or a tidy record summary if the model is offline)
```

### 2.4 The RAG store

| | Patient record | Drug labels |
|---|---|---|
| Source | each saved intake, plus attached notes | 25 verbatim FDA label chunks (`data/label_excerpts.json`) |
| Chunking | one chunk per intake; notes in 800-char pieces with 120 overlap | one chunk per label statement |
| Text | `chunks` table in SQLite | `chunks` table in SQLite |
| Vectors | Chroma collection `patients` | Chroma collection `labels` |
| Retrieval | vector top 6 + BM25 top 6, reciprocal rank fusion (k=60), keep 4, always include the latest intake | every chunk for the drug, in label order |
| Isolation | filter on `patient_id` | filter on `drug` |

Keyword search reads text from SQLite, so retrieval still works when Ollama is down. Vectors can be rebuilt any time from the chunk table (`POST /api/v1/admin/reindex`, or re-run the seed).

### 2.5 Data model (SQLite)

`User` · `Patient` (name required; age, sex optional) · `Intake` (one per visit, with stored eGFR, CrCl, stage, flags) · `Document` · `Chunk` · `Suggestion` (rule result, retrieved ids, model output, final output, status) · `Decision` (accept, edit or reject) · `AuditEvent` (ids and actions only, never names or note text).

### 2.6 Security (POC level)

Password hashes (bcrypt), JWT access tokens (HS256, 60 minutes), role checks through one dependency, an `httpOnly` `SameSite=strict` cookie for the browser, upload limits (5 MB; pdf, txt, md, docx), one standard error body, request ids on every response, JSON logs without patient names.

---

## 3. Code architecture (strict MVC)

```
app/
├── main.py            create_app(): settings, middleware, routers, static files, error handlers
├── core/              config, security, logging, errors, middleware (no business logic)
├── models/            M: domain logic and data. Never imports controllers or views.
│   ├── entities.py, repositories.py, db.py        SQLAlchemy 2.0; all SQL lives in repositories
│   ├── kidney.py                                  Cockcroft-Gault, CKD-EPI 2021, stage, flags
│   ├── dosing_rules.py                            decide() ported unchanged from the dataset generator
│   ├── router.py, retrieval.py, vector_store.py   drug routing; hybrid search; Chroma
│   ├── llm.py, prompts.py, guardrails.py          Ollama client; prompt layout; rule-over-model checks
│   ├── rxd_service.py                             the dosing pipeline
│   ├── chat_service.py                            chat about the selected patient
│   └── patient_service.py, auth_service.py, indexer.py, seed_service.py, ...
├── views/             V: Pydantic schemas (with OpenAPI examples), login.html, app.html, CSS, JS
└── controllers/       C: thin routers. Never import SQLAlchemy, Chroma or httpx.
    ├── api/v1/        auth, patients, intakes, documents, chat, suggestions, rules, audit, admin
    ├── api/health.py  /health and /health/ready
    └── web/pages.py   sign in, sign out and the single screen
data/                  provided kit: prompt, label chunks, rules, 30 synthetic patients, dataset
scripts/               start.sh, seed.py, check_ollama.py, evaluate.py
tests/                 372 tests, including the MVC import rules and parity with the 124 dataset rows
```

### API (`/api/v1`)

| Endpoint | Roles |
|---|---|
| `POST /auth/token`, `GET /auth/me` | public, any |
| `GET /patients`, `POST /patients` (name only required), `GET /patients/{id}` | any, clinician, any |
| `POST /patients/{id}/intakes` (every field optional), `GET /patients/{id}/intakes` | clinician, any |
| `POST /patients/{id}/documents`, `DELETE /documents/{id}` | clinician, pharmacist |
| `POST /chat` | clinician, pharmacist |
| `POST /suggestions`, `GET /suggestions/{id}`, `POST /suggestions/{id}/decision` | clinician+pharmacist, any, clinician |
| `GET /rules`, `GET /audit`, `POST /admin/reindex` | pharmacist+admin, pharmacist+admin, admin |

---

## 4. Decisions worth knowing

- Age and sex are optional. Without them eGFR and CrCl are not calculated, and dosing answers ask for them instead of guessing.
- A gabapentin frequency other than three times daily, or a levofloxacin dose other than 750 or 500 mg, gives "need more information" rather than a guess.
- Chat threads live in the browser tab and are not stored. Suggestions and decisions are stored.
- Oversize uploads return 422 (the handoff's listed codes) rather than 413. A second decision on one suggestion returns 409.
- `/health/ready` is `degraded` (HTTP 200) when only Ollama is missing, and 503 only when the database or vector store is down.
- `verified_by` on every rule is `null`. **A pharmacist must verify each rule before any real use.**
- The primary button is a darker teal than the handoff's `#1FA37A` so white text meets WCAG AA.

---

## 5. Future: from proof of concept to product

Not built. Ordered roughly by when it would matter.

**Safety and clinical validity (first)**
- Pharmacist verification workflow for every rule (`verified_by`), with versioning and an audit trail of rule changes. Block unverified rules in production.
- Full label ingestion (DailyMed PDFs via `scripts/download_labels.py`), more drugs, interaction and age-based rules, pediatric and pregnancy handling.
- Formal evaluation on real, de-identified cases with clinician review; track model agreement, unsafe outputs and time-to-answer as release gates.
- Regulatory review: this is clinical decision support and may count as a medical device.

**Data and integration**
- Replace the form with an EHR connection (FHIR: Patient, Observation for creatinine, MedicationStatement), with consent and data-retention rules.
- Real patient data needs a privacy and security programme (HIPAA or GDPR as applicable): encryption at rest, field-level access, de-identification for logs.
- Structured medication parsing (RxNorm) instead of free text.

**Model**
- Fine-tune the small model on the 124 labelled examples in `data/finetune/` for format, consistency and citation habits. Facts stay in RAG and the rules engine.
- Better embeddings and a reranker; evaluate larger local or private-cloud models. The model name already lives only in `.env`.
- Conversation memory stored per patient and clinician, with retention limits.

**Platform**
- Postgres instead of SQLite; pgvector or a managed vector store instead of local Chroma; migrations (Alembic).
- Containerise; separate the API, a background worker (indexing, reindex) and the model server; queue embedding work.
- Single sign-on (OIDC) with short-lived tokens and refresh, per-clinic tenancy, CSRF protection for cookie auth, rate limits.
- Observability: metrics, tracing, alerting on fallback rate and latency; a proper front-end build if the UI grows beyond one screen.

**Product**
- Voice input for the question box (optional beta from the handoff), patient timeline view, printable summaries, localisation.

---

## 6. Status

| Area | Verified by |
|---|---|
| Kidney formulas, all 124 dataset rows, router, guardrails, fallback, auth and roles, paging, intakes, uploads, per-patient note isolation, chat, decisions, audit, pages | `make test` (all pass, offline) |
| Real model (Ollama, `qwen2.5:1.5b`): dosing explanation, record chat, vectors | live runs; see the evaluation below |
| The screen: sign in, picker, intake form with live preview, chat, verdict card, decisions, phone layout | checked in the browser |

Evaluation results are saved to `storage/eval/<timestamp>.json` by `make eval`.
