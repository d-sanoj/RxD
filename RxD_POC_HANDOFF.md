# RxD — Working Proof of Concept: Build Handoff

> **How to use:** unzip the kit, open Claude Code inside the `rxd_poc_kit` folder (rename it to `rxd-poc` if you like), and send:
>
> *"Read RxD_POC_HANDOFF.md fully. The data/ folder is already provided. Build the project milestone by milestone, run the tests after each one, and stop to ask me if something needs my input."*

---

## 0. What we are building

**RxD** helps a clinician pick a **kidney-safe dose**. At the start of a visit, the clinician records the patient's background (the **visit intake**). RxD stores it in a local **RAG store**. When the clinician asks "can I give this drug?", RxD:

1. calculates kidney function,
2. retrieves the patient's intake and the drug's label rules,
3. applies the label's dose rule, and
4. has a **small local language model** write a short, cited suggestion.

The clinician then accepts, edits or rejects it.

**Scope: a proof of concept that runs fully on one laptop.**
- **Model:** a small language model (SLM) served by **Ollama**. No Kimi, no cloud and no API keys.
- **Retrieval only:** RAG plus a rules engine. **No fine-tuning code is built**; the fine-tuning dataset ships in `data/finetune/` for the presentation.
- **Design:** an end-to-end REST API following standard practice, plus a small web UI, in **strict MVC** inside `app/`.

**Non-negotiables**
1. Synthetic patients only. Show a fixed banner on every page: **"Prototype · synthetic data · not for clinical use."**
2. **The rules engine decides the dose; the model explains it.** The model can never output a dose the rule does not allow (section 6).
3. Every suggestion cites only chunks that were actually retrieved.
4. The app still answers if Ollama is slow or down (deterministic fallback, section 6.4).

---

## 1. What is already in this kit (do not regenerate)

```
data/
  prompts/master_prompt.txt          the system prompt (app and dataset use the same text)
  label_excerpts.json                25 verbatim FDA label chunks for 6 drugs (seed for the "labels" collection)
  dosing_rules.json                  per-drug metadata: kidney measure, product, chunk ids, verified_by
  patients/synthetic_patients.json   30 synthetic patients with backgrounds and visit complaints
  test_set.jsonl                     30 evaluation cases (patient, question, expected action, expected dose)
  finetune/                          train/valid/test.jsonl (124 examples), summary.csv, README.md (dataset card)
scripts/download_labels.py           OPTIONAL: full label PDFs from DailyMed
tools/generate_dataset.py            reproduces everything in data/ (shows how the dataset was built)
```

The **6 drugs** and the kidney measure each label uses:
- by eGFR: metformin, sitagliptin
- by creatinine clearance (CrCl): gabapentin, nitrofurantoin, levofloxacin, famotidine

All rules come word for word from FDA labels (openFDA, retrieved 2026-11-21). `tools/generate_dataset.py` contains the reference rule logic in its `decide()` function. **Port that logic into `app/models/dosing_rules.py` unchanged**, and test that both produce the same answers.

---

## 2. Stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| Web and API | FastAPI + Uvicorn; Jinja2 templates for the UI |
| Validation | Pydantic v2 |
| Database | SQLite via SQLAlchemy 2.0 (`create_all` is fine for a POC) |
| Vector store | ChromaDB `PersistentClient` at `storage/chroma` |
| Keyword search | `rank_bm25` (hybrid with vectors) |
| LLM | **Ollama**, default `qwen2.5:1.5b` (about 1 GB); lighter option `qwen2.5:0.5b` |
| Embeddings | Ollama `nomic-embed-text` |
| Auth | OAuth2 password flow with JWT bearer tokens (FastAPI's standard pattern), plus role-based access |
| Files | `pypdf` and `python-docx` for uploaded notes |
| Testing | pytest, FastAPI TestClient |
| Quality | ruff (lint and format) |

**Why Qwen2.5 1.5B:** it is small, fast on a laptop CPU, good at JSON, and works with Ollama's structured output (`format` set to a JSON schema). Llama 3.2 1B (`llama3.2:1b`) is an acceptable swap. The model name lives only in `.env`.

---

## 3. Strict MVC layout

```
rxd-poc/
├── app/
│   ├── main.py                      # create_app(): settings, middleware, routers, static, error handlers, lifespan
│   ├── core/                        # cross-cutting plumbing, no business logic
│   │   ├── config.py                # pydantic-settings, reads .env
│   │   ├── security.py              # password hashing, JWT create/verify
│   │   ├── logging.py               # JSON logs with request_id
│   │   └── errors.py                # AppError + exception handlers → standard error body
│   ├── models/                      # M: data + domain logic
│   │   ├── db.py                    # engine, session, Base, get_db dependency
│   │   ├── entities.py              # ORM: User, Patient, Intake, Document, Suggestion, Decision, AuditEvent
│   │   ├── repositories.py          # all SQL lives here (PatientRepo, IntakeRepo, SuggestionRepo, AuditRepo)
│   │   ├── kidney.py                # CrCl (Cockcroft-Gault), eGFR (CKD-EPI 2021), stage, flags
│   │   ├── dosing_rules.py          # ported decide() → RuleResult; loads data/dosing_rules.json
│   │   ├── chunking.py              # intake → text chunks; uploads → chunks
│   │   ├── vector_store.py          # Chroma wrapper: "patients" and "labels" collections
│   │   ├── retrieval.py             # hybrid search + reciprocal rank fusion
│   │   ├── llm.py                   # Ollama client (chat + embed), timeouts, retries; FakeLLM for tests
│   │   ├── prompts.py               # loads master_prompt.txt; builds the user message
│   │   ├── guardrails.py            # validates model JSON against RuleResult + retrieved ids
│   │   ├── router.py                # finds the drug in the question; picks a persona
│   │   └── rxd_service.py           # orchestrates the whole suggestion pipeline
│   ├── views/                       # V: everything the client sees
│   │   ├── schemas/                 # Pydantic request/response models (the API's "views")
│   │   │   ├── auth.py  patients.py  intakes.py  documents.py  suggestions.py  common.py
│   │   ├── templates/               # Jinja2 pages and partials
│   │   └── static/                  # css/app.css, js/app.js, img/
│   └── controllers/                 # C: thin routers (parse → call model → return view)
│       ├── api/v1/
│       │   ├── auth.py  patients.py  intakes.py  documents.py  suggestions.py  rules.py  audit.py  health.py
│       └── web/
│           └── pages.py             # HTML pages; they call the same model functions
├── data/                            # provided (section 1)
├── storage/                         # runtime only, git-ignored: rxd.db, chroma/, uploads/
├── scripts/
│   ├── seed.py                      # creates DB, users, patients + intakes; indexes labels + intakes
│   ├── check_ollama.py              # confirms Ollama is running and the models are pulled
│   ├── evaluate.py                  # runs data/test_set.jsonl through the API and prints metrics
│   └── download_labels.py           # provided, optional
├── tests/
├── .env.example  requirements.txt  Makefile  README.md  pyproject.toml (ruff, pytest config)
```

**MVC rules, enforced by `tests/test_architecture.py`:**
- `controllers` must not import `sqlalchemy`, `chromadb` or `httpx`. They only call `models/*_service.py` or the repositories through dependencies.
- `models` must never import from `controllers` or `views`.
- Templates only render; there is no logic beyond loops and `if`.

---

## 4. Data model (SQLite)

- **User**: id, username, password_hash, role (`clinician` | `pharmacist` | `admin`), active
- **Patient**: id ("P001"), name, sex, date_of_birth or age, height_cm, allergies (JSON), created_at
- **Intake** (one per visit; captured at the start of the visit):
  - id, patient_id, visit_date, recorded_by
  - chief_complaint, symptoms (text), history (text), conditions (JSON list), medications (JSON list of {name, dose, frequency}), allergies (JSON)
  - weight_kg (nullable), serum_creatinine_mg_dl (nullable), creatinine_date (nullable), on_dialysis (bool), notes (text)
  - **computed and stored:** crcl, egfr, ckd_stage, flags (JSON)
- **Document**: id, patient_id, filename, uploaded_by, uploaded_at, chunk_count
- **Suggestion**: id, patient_id, intake_id, question, drug, rule_result (JSON), retrieved_ids (JSON), model_name, model_output (JSON), final_output (JSON), status (`ok` | `needs_review` | `blocked` | `fallback`), latency_ms, created_by, created_at
- **Decision**: id, suggestion_id, decision (`accept` | `edit` | `reject`), edited_text, reason, decided_by, decided_at
- **AuditEvent**: id, at, user, action, entity, entity_id, details (JSON)

**Dates:** the seed creatinine dates were set relative to 2026-11-21. If you seed much later, the 90-day stale-lab rule will start flagging patients, so `seed.py` should shift every `scr_date` forward by the number of days between 2026-11-21 and today.

**Seeding (`scripts/seed.py`):** for each patient in `synthetic_patients.json`, create the Patient and **one Intake** from its fields:
- chief complaint = the first visit's `chief_complaint`
- conditions, medications, allergies, weight and creatinine (`scr`, `scr_date`) and dialysis from the patient record
- notes = `background`

Then index every intake into Chroma, and load `label_excerpts.json` into the `labels` collection. Also seed three users from `.env`: `dr.evans` (clinician), `rph.aniket` (pharmacist), `admin.sanoj` (admin). Seeding must be idempotent.

---

## 5. The RAG store

Two Chroma collections, both embedded with `nomic-embed-text`:

| Collection | Contents | Metadata |
|---|---|---|
| `patients` | Each intake turned into readable text (below), plus doctor-uploaded notes | `patient_id`, `source` (intake/upload), `intake_id` or `document_id`, `visit_date` |
| `labels` | The 25 chunks from `label_excerpts.json` (and, optionally, chunks from downloaded PDFs) | `drug`, `chunk_id`, `product`, `source` |

**Intake to text** (`chunking.py`; keep it in one chunk if it is under about 1,200 characters):

```
Visit intake {visit_date} for {name}, {age} {sex}. Chief complaint: {chief_complaint}. Symptoms: {symptoms}.
History: {history}. Conditions: {conditions}. Current medications: {medications}. Allergies: {allergies}.
Weight: {weight_kg or "not recorded"} kg. Serum creatinine {scr} mg/dL on {date}. Dialysis: {yes/no}. Notes: {notes}
```

The chunk id is `PT-{patient_id}-intake-{intake_id}`. Uploads are chunked at 800 characters with a 120-character overlap; their ids are `PT-{patient_id}-doc-{document_id}-{n}`.

**Retrieval** (`retrieval.py`):
- `labels`: filter `drug == <drug>`. Because there are 2–6 chunks per drug, **return all of them** in label order. This keeps the POC simple and complete.
- `patients`: filter `patient_id`, using the question plus the chief complaint as the query. Run a hybrid search (vector top 6 and BM25 top 6), merge with reciprocal rank fusion (k = 60), and keep the top 4. Always include the latest intake chunk.

---

## 6. The suggestion pipeline (`models/rxd_service.py`)

`create_suggestion(patient_id, question, user) -> Suggestion`

1. **Load** the patient and their **latest intake**. If there is no intake, return `422` with "Record a visit intake first."
2. **Kidney** (`kidney.py`), using these reference values in tests:
   - CrCl = ((140 − age) × weight_kg) / (72 × SCr) × 0.85 if female. It is `None` if the weight is missing.
   - eGFR (CKD-EPI 2021) = 142 × min(SCr/κ,1)^α × max(SCr/κ,1)^−1.200 × 0.9938^age × 1.012 if female, where κ is 0.7 (female) or 0.9 (male) and α is −0.241 (female) or −0.302 (male).
   - Stage: G1 ≥ 90, G2 ≥ 60, G3a ≥ 45, G3b ≥ 30, G4 ≥ 15, G5 < 15.
   - Flags: `stale_lab` if the creatinine is more than 90 days old; `missing_weight`; `missing_creatinine`; `dialysis`.
3. **Route** (`router.py`):
   - Find the drug by matching the question (case-insensitive, brand names included, e.g. Januvia, Neurontin, Macrobid, Levaquin, Pepcid, Glucophage).
   - Parse the planned regimen if one is stated (for example "300 mg three times daily" or "750 mg"). Otherwise use the defaults: gabapentin 300 mg three times daily, levofloxacin 750 mg every 24 hours, metformin new start if it is not in the medications list.
   - Choose the persona: `diabetes` (metformin, sitagliptin), `anti_infective` (nitrofurantoin, levofloxacin) or `general` (everything else).
   - An unknown drug skips straight to `insufficient_information`: "This drug is not in RxD's approved sources."
4. **Retrieve** (section 5).
5. **Rule** (`dosing_rules.decide`), which returns `RuleResult{action, dose, max_daily, measure, cite_ids, why, monitoring}`. Data-quality checks come first, exactly as in `tools/generate_dataset.py`: stale lab, then the nitrofurantoin elevated-creatinine case, then missing weight for CrCl drugs.
6. **Generate** (`llm.py`): call Ollama `/api/chat` with:
   - `model` = `RXD_LLM_MODEL`
   - `stream: false`
   - `options: {temperature: 0, num_ctx: 4096}`
   - `format` = the JSON schema from the master prompt (Ollama structured output)
   - messages = `[system: master prompt (+ persona line), user: build_user_message(...)]`. The user message format must match the dataset exactly: PATIENT / KIDNEY / RULE / SOURCES / QUESTION.
   - A 60-second timeout and one retry.
7. **Guardrail** (`guardrails.py`):
   - Parse the JSON; on failure, retry once with "Return only valid JSON."
   - Force `action`, `recommended_dose` and `max_daily_dose` to equal the RuleResult. If the model disagreed, overwrite those fields and set status `needs_review`, recording `"model_disagreed": true`.
   - Drop any citation whose `chunk_id` is not in the retrieved set; if none remain, add the rule's `cite_ids`.
   - `insufficient_information` or any flag gives status `needs_review`; otherwise status `ok`.
8. **Fallback:** if Ollama is unreachable or both tries fail, build `final_output` straight from the RuleResult (its `why` becomes the rationale and its `cite_ids` become the citations), with status `fallback`. **The demo must never fail because of the model.**
9. **Persist** the Suggestion and an AuditEvent, then return.

**Persona lines** appended to the system prompt:
- `diabetes`: "Mention hypoglycemia or lactic-acidosis wording when the sources include it."
- `anti_infective`: "Note when kidney function makes a drug unsuitable, not only the dose."
- `general`: no extra line.

---

## 7. API (REST, versioned, under `/api/v1`)

**Standard practices to follow:**
- **Versioned routes and tags.** OpenAPI docs at `/docs` with an example for every schema.
- **Auth:** `POST /api/v1/auth/token` (OAuth2 password form) returns `{access_token, token_type: "bearer", expires_in}`. Tokens are JWTs signed with HS256 that carry the username and role, and last 60 minutes. Every route except `/health` and `/api/v1/auth/token` requires a bearer token. The web UI stores the token in an httpOnly cookie set by `/login`.
- **Role-based access** through one dependency, `require_roles(...)`.
- **One error body everywhere:** `{"error": {"code": "string", "message": "string", "details": {...}, "request_id": "..."}}`. Use 400/401/403/404/409/422 for client errors and 503 when a dependency is down.
- **Request IDs:** honor an incoming `X-Request-ID` or create a UUID; return it in the response header and include it in every log line.
- **JSON structured logs.** Never log patient names or note text, only ids.
- **Pagination** on list endpoints with `?limit=&offset=`, returning `{items, total, limit, offset}`.
- **Correct status codes:** `201` with a `Location` header on create; `204` on delete.
- **CORS** off by default, configurable in `.env`.
- **Upload limits:** 5 MB maximum; types pdf, txt, md and docx only.
- **Health:** `/health` (liveness) and `/health/ready` (checks the database, Chroma, Ollama and whether the two models are pulled).

| Method and path | Roles | Body → Response |
|---|---|---|
| POST `/api/v1/auth/token` | public | form `username, password` → token |
| GET `/api/v1/auth/me` | any | → `{username, role}` |
| GET `/api/v1/patients` | any | `?q=&limit=&offset=` → paged patients with latest eGFR, CrCl, stage and flags |
| POST `/api/v1/patients` | clinician | `{name, sex, age, height_cm?, allergies[]}` → 201 Patient |
| GET `/api/v1/patients/{id}` | any | → patient + latest intake + kidney + documents |
| POST `/api/v1/patients/{id}/intakes` | clinician | IntakeCreate (section 4) → 201 Intake with computed kidney values; **indexes it into the RAG store** |
| GET `/api/v1/patients/{id}/intakes` | any | → visit history, newest first |
| POST `/api/v1/patients/{id}/documents` | clinician, pharmacist | multipart file → 201 Document; chunked and indexed |
| DELETE `/api/v1/documents/{doc_id}` | clinician, pharmacist | → 204; removes its vectors |
| POST `/api/v1/suggestions` | clinician, pharmacist | `{patient_id, question}` → 201 Suggestion (final_output, kidney, rule, sources, status, latency_ms) |
| GET `/api/v1/suggestions/{id}` | any | → Suggestion |
| GET `/api/v1/patients/{id}/suggestions` | any | → paged history |
| POST `/api/v1/suggestions/{id}/decision` | clinician | `{decision, edited_text?, reason?}` → 201 Decision (reject needs a reason) |
| GET `/api/v1/rules` | pharmacist, admin | → per-drug rules with label chunks and `verified_by` |
| POST `/api/v1/admin/reindex` | admin | → 202; rebuilds both collections |
| GET `/api/v1/audit` | pharmacist, admin | `?limit=&offset=&patient_id=` → paged events |
| GET `/health`, `/health/ready` | public | → status JSON |

---

## 8. Web UI (server-rendered; no front-end framework)

**Look:**
- Calm and clinical.
- Colors: navy `#0E1B2C` sidebar, teal `#1FA37A` primary actions and "ok", paper `#F4F6F8` background, white cards, amber `#B7791F` for needs review, red `#C0392B` for avoid or blocked, muted text `#4A5A6E`.
- System font stack; body text 15px; generous spacing.
- Status is always shown with an icon **and** a word, never by color alone.
- WCAG AA contrast and visible focus rings.

**Pages**
1. **Login:** a centered card listing the three demo accounts.
2. **Patients:** a search box and **New patient** button, and a list of patient cards showing the name, age and sex, an eGFR badge colored by stage, CrCl, the latest visit date, and flag chips. Sorted worst kidney function first.
3. **New visit intake** (the key POC screen): a form in three short steps on one page:
   - (1) Reason for visit: chief complaint and symptoms.
   - (2) Background: history, conditions (chips), medications (repeatable rows: name, dose, frequency), allergies.
   - (3) Measurements: weight, serum creatinine and its date, a dialysis toggle.

   A live preview shows CrCl, eGFR and stage as values are typed (a small JS function using the same formulas, labelled "preview"; the server value is the official one). Saving shows a toast: "Intake saved and added to RxD's knowledge."
4. **Patient detail:**
   - **Left:**
     - Kidney card: large eGFR and CrCl, the stage, the creatinine date, and a "How calculated" expander showing the formula with this patient's numbers.
     - Latest intake summary and visit history.
     - Medications, allergies.
     - The documents upload zone (drag and drop) with a delete button for each document.
   - **Right, "Ask RxD":**
     - Question box with quick chips built from the patient's medications plus the 6 supported drugs ("Check metformin" and so on).
     - On submit: a skeleton card with a live seconds counter.
     - **Suggestion card:**
       - A status strip.
       - A headline such as "Metformin · Avoid".
       - The recommended dose and maximum.
       - The rationale.
       - The kidney measure used.
       - Monitoring.
       - **Sources**: expandable items with the chunk text, labelled "FDA label · product" or "Visit intake · date" or "Uploaded note · filename".
       - Small print: the model name, latency and suggestion id.
     - **Accept / Edit / Reject** buttons (clinicians only); Reject asks for a reason.
     - History of earlier suggestions with their decisions.
5. **Rules** (pharmacist, admin): each drug's label chunks and its verified or not-yet-verified badge.
6. **Audit** (pharmacist, admin): a filterable table.

---

## 9. Configuration (`.env.example`)

```
RXD_ENV=dev
RXD_DB_URL=sqlite:///storage/rxd.db
RXD_CHROMA_DIR=storage/chroma
RXD_UPLOAD_DIR=storage/uploads
RXD_DATA_DIR=data
OLLAMA_URL=http://localhost:11434
RXD_LLM_MODEL=qwen2.5:1.5b
RXD_EMBED_MODEL=nomic-embed-text
RXD_LLM_TIMEOUT_S=60
RXD_JWT_SECRET=change-me-to-a-long-random-string
RXD_JWT_TTL_MIN=60
RXD_CORS_ORIGINS=
RXD_MAX_UPLOAD_MB=5
RXD_SEED_PW_CLINICIAN=demo-clinician
RXD_SEED_PW_PHARMACIST=demo-pharmacist
RXD_SEED_PW_ADMIN=demo-admin
```

---

## 10. Tests (`make test` must pass with Ollama **off**, using FakeLLM and fake embeddings)

- **`test_kidney.py`** (tolerance ±0.2):
  - eGFR: male 60, SCr 1.0 → 86.2; female 50, SCr 0.7 → 105.3; female 72, SCr 2.0 → 26.1.
  - CrCl: female 72, 60 kg, SCr 2.0 → 24.1; male 45, 85 kg, SCr 1.2 → 93.5.
  - Stage boundaries; flags.
- **`test_dosing_rules.py`:** for **every** row of `data/finetune/summary.csv` (it has age, sex, weight, creatinine, lab age in days, eGFR, CrCl, dialysis and the scenario), rebuild the inputs and assert that `dosing_rules.decide` gives the same `expected_action` and `recommended_dose`. Take each scenario's planned regimen from the `SCENARIOS` dictionary in `tools/generate_dataset.py` (copy the dictionary into a test fixture; importing that script would regenerate the data files). Use the CSV's `lab_age_days`, not today's date, because the dataset was built on 2026-11-21. This proves the app matches the dataset.
- **`test_guardrails.py`:** the model disagrees with the rule (overwritten, `needs_review`); a fake chunk_id (dropped); bad JSON (retry, then fallback); Ollama down (`fallback`).
- **`test_api.py`:** token login; 401 without a token; 403 for the wrong role; create a patient, then an intake (kidney values computed and the intake indexed); upload and delete a document; create a suggestion for P001 metformin (`action == "avoid"`); record a decision; paging; the error body shape; the request id header.
- **`test_architecture.py`:** the MVC import rules (section 3).

---

## 11. Evaluation (`scripts/evaluate.py`): ties to our R.3 metrics

Run `data/test_set.jsonl` (30 cases) against the running API with the real model, and print:

| Metric | R.3 link | Pass bar |
|---|---|---|
| Median and p90 latency | Time to a dose answer (target 30 s or less) | median ≤ 30 s on a laptop CPU |
| Action matches expected | Suggestion accuracy | ≥ 95% (100% is expected, because the rules decide) |
| Unsafe outputs (a dose or action outside the rule) | Zero unsafe doses | **0** |
| Citation validity | Grounding | 100% |
| Model agreed with the rule before the guardrail | Model quality | report the % (a fine-tuning story for the pitch) |
| Fallback rate | Reliability | report |

Save the results to `storage/eval/<timestamp>.json` and print a short table for the demo.

---

## 12. Run it

```bash
# 1. Ollama (https://ollama.com/download), then pull the two small models (~1.3 GB total)
ollama pull qwen2.5:1.5b
ollama pull nomic-embed-text
ollama run qwen2.5:1.5b "Reply with OK"      # sanity check

# 2. Python
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env

# 3. Check, seed, run
python scripts/check_ollama.py
python scripts/seed.py
uvicorn app.main:app --reload
# UI:  http://localhost:8000      API docs: http://localhost:8000/docs
# Login: dr.evans / demo-clinician

# 4. Measure
python scripts/evaluate.py
```

The Makefile provides: `make setup`, `make models` (the two `ollama pull` commands), `make seed`, `make run`, `make test`, `make eval`, `make lint`.

**Low-memory laptops:** set `RXD_LLM_MODEL=qwen2.5:0.5b`.

---

## 13. Milestones (check the acceptance line before moving on)

1. **Skeleton and auth:** app factory, settings, error handler, request id, logging, `/health`, the token endpoint, roles, base layout and banner. *Accept:* login works for each role; architecture test passes.
2. **Patients and intake:** entities, repositories, the patient and intake endpoints, the kidney calculations, the patients list, and the intake form with live preview. *Accept:* the P001 intake shows eGFR 26.1 and CrCl 24.1; the kidney tests pass.
3. **RAG store:** seed, both collections, intake indexing on save, document upload and delete, hybrid retrieval. *Accept:* a new intake for a patient is returned by retrieval immediately; deleting a document removes its chunks.
4. **Rules:** port `decide()`; the dataset-parity test. *Accept:* `test_dosing_rules.py` passes for all 124 examples.
5. **Suggestions:** prompt building, the Ollama call with structured output, guardrails, fallback, the decision endpoint, audit. *Accept:* P001 "Is metformin 1000 mg twice daily still OK?" returns **Avoid**, citing `LBL-metformin-04` and the intake, in under 30 seconds; with Ollama stopped it returns status `fallback` with the same action.
6. **UI polish:** the suggestion card, sources, history, rules and audit pages. *Accept:* the full demo flow works with the keyboard alone.
7. **Evaluation and README:** `evaluate.py` and screenshots. *Accept:* 0 unsafe outputs, and the eval table prints.
8. *(Optional)* **Voice input beta:** `faster-whisper` (`base.en`) behind `RXD_ENABLE_VOICE=false`; a mic button fills the question box for the clinician to check before sending.

---

## 14. Demo script for the pitch (60 seconds)

1. Log in as `dr.evans`. Open **Maria Lopez (synthetic)**: eGFR 26, CrCl 24, stage G4.
2. Ask "Is metformin 1000 mg twice daily still OK?" The answer is **Avoid**: the label says to discontinue below an eGFR of 30, and RxD shows the label quote and the intake as sources.
3. Click **Check gabapentin** (planned 300 mg three times daily). The answer is **Adjust dose: 200 mg once daily** (CrCl 15–29 band).
4. Create a new patient (male, 50, 80 kg), record a **visit intake** for heartburn with a creatinine of 1.0 mg/dL dated today, and ask "Starting famotidine 20 mg twice daily for heartburn. What is the right dose?" The answer is **Continue: 20 mg twice daily** (CrCl about 100), which shows the new intake flowing straight into the RAG store.
5. Open **/docs** to show the versioned REST API, then show `data/finetune/README.md` to explain the next step: fine-tuning on 124 labelled examples.

---

## 15. Ask the user rather than guess

- If Ollama is not installed, or a model pull fails.
- If they want Llama 3.2 1B instead of Qwen 2.5 1.5B.
- **Never set `verified_by` on a rule. A pharmacist (a person) must do that.**
