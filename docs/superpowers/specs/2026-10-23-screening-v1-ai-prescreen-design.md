---
status: draft
last_reviewed: 2026-10-23
owner: '@raphaelfh'
---

# Screening v1: PubMed import, human review, then AI pre-screen — design

> **Status:** Draft, revision 2 (after the review on #1048) · Proposed by
> @fabianofilho · Narrows
> [`2026-05-03-screening-and-imports-design.md`](2026-05-03-screening-and-imports-design.md)
> (Phase α) and pulls one piece of its Phase β (an AI suggestion per article)
> forward. Where this document is silent, the 05-03 design still applies;
> where they disagree, this one wins for v1 and §3 says why.

## 1. Why now, and the first real dataset

prumo has no screening stage: the sidebar shows `screening` and `prisma` as
`comingSoon` (`frontend/components/layout/sidebarConfig.ts:54`, `:57`).
Reviews screen elsewhere (Rayyan) and re-import the included set, which
breaks the audit trail the rest of prumo keeps.

The first review to run through v1 is a LABDAPS scoping of **MIMIC-IV AND
machine learning** (PubMed, exported 2026-10-21):

| Fact | Value |
| --- | --- |
| Records | 1,976 |
| With DOI / with PMID | 1,959 / 1,976 |
| Publication year | 2026: 791 · 2025: 674 · 2024: 265 · 2023: 144 · ≤2022: 101 · 2027: 1 |
| Columns in the PubMed CSV export | PMID, Title, Authors, Citation, First Author, Journal/Book, Publication Year, Create Date, PMCID, NIHMS ID, DOI |
| **Abstract in the export** | **no** |

The CSV export has no abstract. Screening on titles alone is weak for
humans and for a model, so **import fetches the record from PubMed by
PMID** (E-utilities `efetch`), which also brings MeSH terms, full author
names and publication types.

Success for v1 = this review goes from the PubMed CSV to a PRISMA-ready
title/abstract count inside prumo, with every AI suggestion traceable to the
exact text, criteria and engine it ran under, and with the AI's recall on
this dataset measurable from blind human decisions before anyone leans on it.

## 2. Scope

**Slice A, human only (PR 2):**

1. **Import** a PubMed result set by PMID (CSV upload or pasted PMIDs),
   through the existing canonical-identity import path, deduplicated exactly
   on PMID and normalized DOI.
2. **Title/abstract screening**, solo or dual (2–3 reviewers), unanimous
   consensus, the project's arbitrators for conflicts, blind mode.
3. **PRISMA counts** for the identification and screening boxes.

**Slice B, AI (PR 3):**

1. **AI pre-screen**: per article, a per-criterion verdict with a quote from
   the title/abstract, an overall suggestion and a confidence, or a recorded
   `no_abstract` / `failed` outcome. Always a proposal; a human records every
   decision.
2. **Calibration report**, computed on read from the decisions reviewers
   made with AI hidden, against the AI suggestions for the same records.
3. **AI-use statement** for the methods section, built from stored rows.

**Not in v1:** full-text phase and Unpaywall · fuzzy dedup (it lands with a
second import source) · notes · per-user shortcut preferences · smart filters
· `⌘K` palette entries · Scopus/WoS CSV · RIS through the new path (RIS stays
on its current path) · PDF import · `articles.screening_status` (lands with
extraction gating) · active learning and stop criteria · kappa · MCP tools
for screening · AI auto-exclusion of any kind.

**Anti-goals**

- An AI verdict that changes an outcome without a human decision.
- A suggestion whose input text, prompt, criteria or engine cannot be
  recovered.
- A reviewer able to read a peer's decision, or an AI suggestion while AI is
  hidden, by any path (API or PostgREST) before the outcome publishes.
- A second write path for articles.

## 3. Where v1 departs from the 05-03 design, and why

| 05-03 says | v1 does | Why |
| --- | --- | --- |
| Postgres enums in a Supabase migration (§4.1) | `text` + `CHECK` in Alembic | AGENTS.md: app schema is Alembic only; 0091–0093 use `CheckConstraint`. |
| `screening_criterion` table + `pico_summary` | **No criteria table.** Criteria come from the stored protocol: PICOTS slot `inclusion[]`/`exclusion[]` and `eligibility_criteria.inclusion[]`/`.exclusion[]` | ADR 0023 already renders these into every AI call (`project_ai_context.render_review_question`), versioned by `protocol_revision` (0088). |
| `screening_decision.ai_suggestion_id → ai_suggestions(id)` | FK to `screening_ai_suggestions`, set by the server | `ai_suggestions` was dropped (`archive/20260428_0019_drop_ai_suggestions.py`). |
| `ai_usage_log` table | `ai_usage_ledger` (0091) with `pass_kind = 'screen'` | One ledger for all model calls (#1022). |
| `screening_phase_config.arbitrator_id` | No column; arbitration uses `ensure_project_arbitrator` (`is_project_arbitrator`: manager or consensus role) | One definition of "arbitrator". |
| New `/imports/*` module, `ArticleImportService` | PubMed joins the Zotero path: `normalize_pubmed_record` → `CanonicalArticlePayload` → `ArticleRepository.upsert_by_canonical_identity`, one `article_sync_runs` row per import (`source = 'pubmed'`) | The create path and per-import counts already exist. |
| DOI + fuzzy dedup with a review panel, `rapidfuzz` | Exact PMID / normalized DOI only | 1,976/1,976 records carry a PMID and PubMed is the only source. Fuzzy matching lands with the second source, on `pg_trgm` (`idx_articles_trgm_title` exists). |
| `articles.screening_status` + triggers | Not in v1 | Nothing reads it before extraction gating; it duplicates the outcomes. |
| Member-read RLS policies | Backend-only tables (RLS on, `REVOKE ALL FROM anon, authenticated`) | Member-read would reopen the blind-review leak closed by `0025_reviewer_scoped_select_rls`. Every read goes through the API, which applies blind/reveal. |
| One decision row per reviewer, `version` bumps | Append-only decisions and outcomes; the current row is the one with `superseded_by IS NULL`, enforced by a partial unique index | Constitution §IX: human selections are append-only. |
| AI in Phase β | AI in v1, as its own slice after the human-only one | The first dataset has ~2,000 records; the ask is a pre-screen with human review. |
| PubMed query builder | PMID list | The user already has the export; `esearch` can feed the same path later. |

## 4. Import (slice A)

### 4.1 Flow

```
PubMed CSV / pasted PMIDs
  → browser: papaparse, keep the PMID column (≤ 10,000 PMIDs, ≤ 25 MB)
  → POST /api/v1/projects/{project_id}/imports/pubmed  {pmids[], dry_run?}
      backend: efetch in batches of 200 (≤ 3 req/s, ≤ 10 with NCBI_API_KEY),
               normalize_pubmed_record → CanonicalArticlePayload,
               upsert_by_canonical_identity per record
      ← {received, inserted, updated, duplicates_in_request, not_found[], failed}
```

- **Idempotent.** Posting the same PMIDs twice updates the same articles and
  inserts nothing new. `dry_run = true` returns the counts and writes
  nothing, so the dialog can show what will happen before the user confirms.
- One `article_sync_runs` row per non-dry-run call: `source = 'pubmed'`,
  `total_received`, `persisted`, `updated`, `skipped` (duplicates in the
  request), `failed`, and `failure_summary` with the PMIDs NCBI did not
  return.
- Runs inline for ≤ 1,000 PMIDs; above that, the same service runs in the
  existing import Celery queue and the dialog polls the sync run (author's
  call; 1,976 PMIDs at 200 per call and 3 req/s is ~4 s of NCBI time, so
  inline may well be enough).
- Role: `ensure_project_manager`, as the Zotero import.

### 4.2 Normalization and identity

- `normalize_pubmed_record` in `services/article_source_normalization.py`
  next to `normalize_zotero_item`, reusing `normalize_doi` and
  `extract_year`. Fields: title, abstract (structured abstracts joined with
  their labels), authors (`Last, Initials`), journal, year/month/day,
  volume, issue, pages, doi, pmid, pmcid, mesh_terms, keywords,
  article_type (first publication type), language;
  `ingestion_source = 'pubmed'`; the raw efetch XML fragment goes to
  `source_payload`.
- `get_by_canonical_identity` gains `pmid` (today it matches
  `zotero_item_key`, `doi` and `url_landing`). Match order: pmid, doi,
  url_landing.
- The NCBI client takes an injectable `httpx` transport, so tests use an
  `httpx.MockTransport` over `backend/tests/fixtures/pubmed/`.

## 5. Data model (Alembic `0094_screening_v1`)

**Every table is backend-only**, like `0075`/`0076`/`0091`:
`ENABLE ROW LEVEL SECURITY` and `REVOKE ALL ... FROM anon, authenticated`.
The API is the only reader and applies blind/reveal in the service read
path. `text` + `CHECK` for kinds.

```text
screening_configs            one per project (v1: title/abstract only)
  project_id (unique), reviewer_count 1..3, blind_mode,
  ai_visible (default false), created_by, timestamps

screening_assignments        an article enrolled in screening
  id, project_id, article_id, phase ('title_abstract'), enrolled_at
  UNIQUE (project_id, article_id, phase)
  queue order: ORDER BY md5(id::text)  (stable pseudo-random, see §6.3)

screening_decisions          append-only; one row per revision
  id, assignment_id, reviewer_id, decision ('include'|'exclude'|'maybe'),
  exclusion_reason (one of the protocol's exclusion strings, snapshotted),
  rationale, ai_suggestion_id (server-set; NULL when AI was hidden),
  ai_visible_at_decision (server-set from the config), superseded_by,
  created_at
  partial UNIQUE (assignment_id, reviewer_id) WHERE superseded_by IS NULL

screening_outcomes           append-only; the published result
  id, assignment_id, decision, exclusion_reason,
  source ('solo'|'consensus'|'arbitrated'),
  decided_by (arbitrator, when arbitrated), selected_decision_id,
  rationale, superseded_by, decided_at
  partial UNIQUE (assignment_id) WHERE superseded_by IS NULL

screening_ai_runs            one per AI pre-screen request (slice B)
  id, project_id, status ('pending'|'running'|'completed'|'failed'|'cancelled'),
  parameters jsonb  (frozen once at start: pinned engine, prompt name and
                     version, protocol_revision, the rendered review question
                     and system prompt in the PromptComposition shape,
                     assignment selection),
  error_message, created_by, timestamps

screening_ai_suggestions     append-only; one per (run, assignment) (slice B)
  id, run_id, assignment_id,
  outcome ('ok'|'no_abstract'|'failed'),
  suggestion, confidence, criteria jsonb, reason   (NULL unless outcome = 'ok', CHECK)
  text_sha256 (title + abstract as sent), usage jsonb, request_id, created_at
  UNIQUE (run_id, assignment_id)

ai_usage_ledger.pass_kind    CHECK widened with 'screen'
```

`criteria[]` items are `{key, kind, text, verdict ('met'|'not_met'|'unclear'),
quote, quote_verified}`. `key` is a stable hash of (source slot, kind,
text), so a criterion keeps its key across runs while its text is
unchanged.

Status, progress and counts are derived from rows, never stored: an
assignment is "awaiting me", "awaiting peer", "in conflict" or "decided"
from its current decisions and outcome; a run's progress is its suggestion
count over its selection size.

## 6. AI pre-screen (slice B)

### 6.1 One call per article

- **Engine pinned per run.** `POST .../ai-prescreen` resolves the project's
  engine once (`resolve_engine` with the project default, then
  `resolve_engine_credentials`), and freezes it in
  `screening_ai_runs.parameters`, as `run_engine_freeze` does for
  extraction. Every call in the run reads the pinned engine, so a run never
  mixes engines and the calibration report can group by it.
- Calls go through `metered(extract_structured, LedgerSink(...), ctx)` with
  a new prompt `screening_title_abstract`, registered in `llm/pass_kinds.py`
  as `'screen'`.
- Input: the rendered review question (frozen in the run), the numbered
  criteria, title and abstract. Nothing else (no journal, no authors).
- Output (pydantic): per criterion `{key, verdict, quote}`, overall
  `{suggestion, confidence, reason}`.
- **Quote check:** `quote_verified` is true only when the quote is a
  whitespace-normalized substring of the title or abstract that was sent. An
  unverified quote shows a "verify manually" badge, as extraction does.
- **Display rule (author's call, recall-first):** the stored suggestion is
  the model's; the UI shows `exclude` only when every inclusion criterion is
  `not_met` or an exclusion criterion is `met` with a verified quote, and
  `maybe` otherwise.
- **No abstract** → no model call, a row with `outcome = 'no_abstract'`.
  **Call failure** → a row with `outcome = 'failed'` (the ledger row carries
  the failure). "No information" is a recorded outcome, never a missing row.

### 6.2 Running a pre-screen

One Celery task per run: it takes the next chunk of assignments without a
suggestion in this run, writes one row each with
`INSERT ... ON CONFLICT (run_id, assignment_id) DO NOTHING`, and re-enqueues
itself until none are left or the run is cancelled. A retried or duplicated
task cannot write twice. The engine precheck and queue probe run before the
run is created, as in `ExtractionBatchService.start`; the endpoint commits,
then kicks the task. The frontend polls the run only while it is active.

### 6.3 Calibration, computed on read

No gate and no calibration state. Instead:

- The queue serves assignments in a stable pseudo-random order
  (`ORDER BY md5(id::text)`), so the first N records any reviewer screens
  are a random sample of the enrolled set, without drawing one.
- While `ai_visible` is false, reviewers decide without seeing suggestions;
  the server records `ai_visible_at_decision = false`.
- `GET /projects/{id}/screening/calibration` compares the published
  outcomes of assignments whose decisions were all made with AI hidden
  against the AI suggestions for the same assignments, grouped by (pinned
  engine, prompt version, protocol revision). Positive = include or maybe.
  It returns recall and specificity with 95% Wilson intervals, the number of
  human includes they rest on, how many human includes the display rule
  would have shown as `exclude`, and the disagreements with both sides'
  reasons.
- The manager reads that report and then turns `ai_visible` on. prumo does
  not decide a threshold. A change of engine, prompt or protocol starts a
  new group in the report, so there is nothing to reopen.

For scale: pooled LLM sensitivity in a 2025 meta-analysis was 0.812 (95% CI
0.617–0.920) with very high heterogeneity [3], and a 2025 review found the
best approaches near 95–97% recall, none consistently at the 99% its authors
consider necessary to replace a human [4]. A model change is reported to
shift recall [5]. With ~10 human includes in 150 records the interval is
wide, which is why the report always shows the count it rests on.

## 7. Human review (slice A)

- Queue: one article at a time, title + abstract with criterion terms
  highlighted, keys `1` include / `2` exclude / `3` maybe / `e` exclude with
  reason (reasons = the protocol's exclusion strings, numbered). The AI
  panel appears only when `ai_visible` is true (slice B).
- Solo: the decision publishes an outcome (`source = 'solo'`).
- Dual: an outcome publishes when all `reviewer_count` current decisions
  agree (`consensus`); any disagreement puts the assignment on the conflicts
  list, where a project arbitrator adopts one decision or overrides with a
  rationale (`arbitrated`). Conflict detection reads current decisions
  ordered by `(created_at, id)`.
- Changing a decision appends a new row and supersedes the old one; if an
  outcome had published, it is superseded too and the assignment goes back
  to consensus (solo: the new decision publishes a new outcome).
- Blind mode: the read path returns other reviewers' current decisions only
  after the outcome publishes (the reveal idea of ADR 0012, applied in the
  screening read service).

## 8. PRISMA counts (slice A)

Read-only, derived:

- **Identified**: enrolled assignments grouped by
  `lower(articles.ingestion_source)`, so RIS, Zotero and manual articles
  count too.
- **Duplicates removed**: the `updated` + `skipped` counts of the project's
  `article_sync_runs`.
- **Screened / excluded / sought for retrieval**: current outcomes at
  title/abstract (excluded with reason counts; sought = include + maybe).

Shown on the `prisma` tab as numbers; the diagram is v2.

**AI-use statement (slice B).** The same tab renders a copyable methods
paragraph built only from stored rows: engine and model, prompt name and
version, dates of use, purpose (pre-screen suggestion, never applied without
a human decision), reviewers per record and how conflicts were resolved,
and the calibration figures with their intervals and counts. This is what
the Cochrane/Campbell/JBI/CEE position statement asks authors to report [1],
and what the proposed PRISMA-trAIce items on human oversight and performance
cover [2].

## 9. API and guards

All under `/api/v1`, `ApiResponse` envelope.

| Route | Role guard | Binding |
| --- | --- | --- |
| `POST /projects/{id}/imports/pubmed` | `ensure_project_manager` | project from path |
| `GET /projects/{id}/screening/config` | `ensure_project_member` | project from path |
| `PUT /projects/{id}/screening/config` | `ensure_project_manager` | project from path |
| `POST /projects/{id}/screening/enroll` | `ensure_project_manager` | article ids through `article_read_service.owned_articles` |
| `GET /projects/{id}/screening/queue` | `ensure_project_reviewer` | project from path |
| `GET /screening/assignments/{aid}` | `ensure_project_member` on the assignment's project | new guard `owned_assignment` (assignment by id, project resolved from the row, as `load_run_for_member`) |
| `POST /screening/assignments/{aid}/decisions` | `ensure_project_reviewer` | `owned_assignment`; `ai_suggestion_id` and `ai_visible_at_decision` set by the server |
| `GET /projects/{id}/screening/conflicts` | `ensure_project_arbitrator` | project from path |
| `POST /screening/assignments/{aid}/arbitration` | `ensure_project_arbitrator` | `owned_assignment`; `selected_decision_id` bound by `assignment_id` in the WHERE clause |
| `POST /projects/{id}/screening/ai-prescreen` | `ensure_project_manager`, then `assert_engine_ready` | assignment selection bound by project in the WHERE clause |
| `GET /screening/ai-runs/{rid}` · `POST .../cancel` | member · manager | new guard `owned_screening_ai_run` |
| `GET /projects/{id}/screening/calibration` | `ensure_project_member` | project from path |
| `GET /projects/{id}/prisma` | `ensure_project_member` | project from path |

The two new guards are added to `.claude/rules/backend.md` § Ownership
guards in the PR that introduces them.

## 10. Frontend

- `screening` and `prisma` tabs lose `comingSoon`.
- Screening tab states: not configured → configure (reviewers, blind) ·
  nothing enrolled → "Import from PubMed" / "Enroll all" · queue · conflicts
  (arbitrators) · done. Slice B adds the AI panel, the "Run AI pre-screen"
  action, the calibration report and the `ai_visible` switch beside it.
- Import dialog: drop the PubMed CSV or paste PMIDs → dry-run counts →
  confirm. The articles list source filter gains a PubMed option (sources
  are compared case-insensitively: the backend writes `zotero` and
  `pubmed`, the manual form writes `MANUAL`).
- Copy in `frontend/lib/copy/screening.ts`; hooks under
  `frontend/hooks/screening/`; services in
  `frontend/services/screeningService.ts`; every read through the API.

## 11. Delivery as stacked PRs

1. `docs(specs)`: this document.
2. `feat(screening)`: slice A. PubMed import on the canonical path, the
   migration for configs/assignments/decisions/outcomes, enroll, queue,
   decisions, conflicts and arbitration, blind mode, PRISMA counts, the
   Screening and PRISMA tabs. Usable on its own as human-only screening.
3. `feat(screening)`: slice B. AI runs and suggestions tables, the
   `'screen'` pass kind, the prompt, the run task, the AI panel, the
   calibration report, `ai_visible`, the AI-use statement.

## 12. Tests

- **Unit**: PubMed XML → normalized record (fixtures from real efetch
  responses in `backend/tests/fixtures/pubmed/`); identity match order;
  quote verification; the display rule; Wilson interval; criterion keys
  stable across runs; outcome CHECK (payload NULL unless ok).
- **Integration** (real local Supabase): import idempotency and `dry_run`
  writes nothing; the `article_sync_runs` counts; solo, dual and
  3-reviewer outcomes; deterministic conflicts regardless of insert order;
  superseding a decision supersedes its outcome; blind masking in the read
  path; **RLS: `authenticated` reads zero rows from every screening table
  through PostgREST**; reviewer vs viewer on the decision route; a forged
  `selected_decision_id` from another assignment is refused; a suggestion
  run is idempotent under a duplicated task; `no_abstract` and `failed`
  rows; the run's frozen parameters; ledger rows with `pass_kind = 'screen'`.
- The 05-03 §12.3 PR #7 regression list applies where its tables still exist.
- **Frontend**: vitest for the queue hook (optimistic advance, rollback),
  the keyboard map and the import dialog counts. One Playwright flow that
  starts at enroll on seeded articles (no NCBI): decide, resolve a conflict,
  read the PRISMA counts.
- **Post-merge validation, not a merge gate**: the 1,976-record MIMIC-IV
  export through import, blind screening of a prefix of the queue, and the
  calibration report, with the numbers posted on the slice-B PR.

## 13. Questions and answers

Answered in the review of revision 1: fuzzy dedup waits for the second
source and will use `pg_trgm` (Q1); RIS stays on its current path (Q2).

Still open:

1. NCBI asks for `tool` and `email` on E-utilities calls: a new
   `NCBI_EMAIL` setting plus an optional `NCBI_API_KEY`, or an existing
   contact setting?
2. The recall-first display rule (§6.1) is the proposer's call; change it
   here before PR 3 if you prefer the model's raw suggestion.
3. Append-only via `superseded_by` with a partial unique index, rather
   than extraction's separate reviewer-states table, is the proposer's call
   (one table per concept instead of two). Say so if you want the
   extraction shape mirrored.

## 14. References

Only sources whose text was opened are cited. RAISE (the Cochrane/Campbell/
JBI/CEE guidance on responsible AI in evidence synthesis) supports the same
validate-and-report principle but its documents were not read for this
design, so it is not cited for any specific claim.

1. Flemyng E, Noel-Storr A, Macura B, et al. Position statement on
   artificial intelligence (AI) use in evidence synthesis across Cochrane,
   the Campbell Collaboration, JBI and the Collaboration for Environmental
   Evidence 2025. *JBI Evid Synth* 2025;23(11):2162-2166.
   doi:10.11124/JBIES-25-00480 — human oversight; transparent reporting of
   tool, version, date and purpose; validate before relying on it.
2. Holst D, Moenck K, Koch J, Schmedemann O, Schüppstuhl T. PRISMA-trAIce
   checklist. *JMIR AI* 2025;4:e80247. doi:10.2196/80247 — a proposed (not
   PRISMA-endorsed) extension; items on human oversight, reference standard
   and AI–human performance.
3. Kim JK, Rickard M, Dangle P, et al. Evaluating large language models for
   title/abstract screening: a systematic review and meta-analysis. *J Med
   Artif Intell* 2025;8:34. doi:10.21037/jmai-24-408 — pooled sensitivity
   0.812 (0.617–0.920), false-positive rate 0.110, I² 91.6–99.7%.
4. Sandner E, Fontana L, Kothari K, et al. Evaluating LLMs for literature
   screening: a systematic review of sensitivity and workload reduction.
   *Proc. DATA* 2025:508-517. doi:10.5220/0013562900003967 — six approaches
   reached ≥95% sensitivity (max 97%), none consistently 99%; workload
   reduction 48–79%.
5. Fagerberg P, Sallander O, Vikhe Patil K, et al. Audited LLM triage for
   systematic review screening in national clinical guideline production.
   *medRxiv* 2026 (preprint, not peer reviewed).
   doi:10.64898/2026.06.02.26354724 — only unanimous AI exclusions across
   repeated runs enter the AI-excluded pool; prospective audit of excluded
   records; revalidate when the model changes.
