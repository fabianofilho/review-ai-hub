---
status: draft
last_reviewed: 2026-10-23
owner: '@raphaelfh'
---

# Screening v1: PubMed import, dedup, AI pre-screen and human review — design

> **Status:** Draft · Proposed by @fabianofilho · Narrows
> [`2026-05-03-screening-and-imports-design.md`](2026-05-03-screening-and-imports-design.md)
> (Phase α) and pulls one piece of its Phase β (AI suggestion per article)
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
humans and for a model, so **import must fetch the record from PubMed by
PMID** (E-utilities `efetch`), which also brings MeSH terms, full author
names and publication types.

Success for v1 = this review goes from the PubMed CSV to a PRISMA-ready
title/abstract count inside prumo, with every AI suggestion traceable to the
exact text and criteria it saw, and with the AI's recall measured on this
dataset before anyone leans on it.

## 2. Scope

**In v1**

1. **Import** a PubMed result set by PMID: upload the PubMed CSV (or paste
   PMIDs) → backend `efetch` → normalize → dedup → preview → confirm.
2. **Dedup** at import: exact on PMID and normalized DOI, fuzzy on
   (title, first author, year) per 05-03 §8.2, with a review panel for the
   uncertain band.
3. **Title/abstract screening** only, solo or dual (2–3 reviewers),
   unanimous consensus, arbitrator for conflicts, blind mode.
4. **AI pre-screen**: per article, a per-criterion verdict with a quote from
   the title/abstract, an overall suggestion and a confidence. Always a
   proposal; a human records every decision.
5. **Calibration sample**: before the AI suggests on the whole set, a random
   sample is screened blind by the humans and by the AI, and prumo reports
   the AI's recall and specificity against the human outcome.
6. **PRISMA counts** for the identification and screening boxes, plus an
   AI-use statement for the methods section built from stored rows.

**Not in v1** (deferred, unchanged from 05-03 unless stated): full-text
phase and Unpaywall · notes · per-user shortcut preferences · smart filters
· `⌘K` palette entries · Scopus/WoS CSV and RIS through the new path · PDF
import · active learning and stop criteria · kappa · MCP tools for
screening · AI auto-exclusion of any kind.

**Anti-goals**

- An AI verdict that changes `screening_status` without a human decision.
- A suggestion whose input text, criteria or engine cannot be recovered.
- Showing the AI suggestion to a reviewer *before* their own decision during
  calibration (it would contaminate the measurement).
- A second write path for articles (the RIS dialog's direct Supabase insert,
  `frontend/components/articles/RISImportDialog.tsx:88`, is the pattern this
  replaces for the new source, not one to copy).

## 3. Where v1 departs from the 05-03 design, and why

| 05-03 says | v1 does | Why |
| --- | --- | --- |
| Postgres enums in a Supabase migration (§4.1) | `text` + `CHECK` in one Alembic migration | AGENTS.md: app schema is Alembic only; recent migrations (0091–0093) use `CheckConstraint`, not enums. |
| `screening_criterion` table + `pico_summary` on the phase config | **No criteria table.** Criteria come from the project protocol already stored: PICOTS slot `inclusion[]`/`exclusion[]` and `eligibility_criteria.inclusion[]`/`.exclusion[]` | ADR 0023 already renders these into every AI call through `project_ai_context.render_review_question`, and `protocol_revision` versions them. A second list would drift from the one the AI sees. |
| `screening_decision.ai_suggestion_id → ai_suggestions(id)` | FK to a new `screening_ai_suggestions` table | `ai_suggestions` was dropped (`alembic/versions/archive/20260428_0019_drop_ai_suggestions.py`). |
| `ai_usage_log` table | Reuse `ai_usage_ledger` (0091) with a new `pass_kind = 'screen'` | One ledger for all model calls (#1022). |
| AI in Phase β | AI suggestion in v1, behind the calibration gate | The first dataset has ~2,000 records; the ask is a pre-screen with human review. |
| Fuzzy ≥ 0.95 auto-merged (§8.2) | Every fuzzy match ≥ 0.85 confirmed by a human | Conservative dedup: a wrongly merged record is a silently lost study [6, 7]. |
| PubMed query builder | PMID list (CSV upload or paste) | The user already has the export; `esearch` can come later on the same `efetch` path. |
| 8 tables | 6 tables (§5) | Notes, preferences and criteria are out (§2, §3 row 2). |

## 4. Import

### 4.1 Flow

```
PubMed CSV / pasted PMIDs
  → browser: papaparse, keep the PMID column (≤ 10,000 PMIDs, ≤ 25 MB)
  → POST /api/v1/screening/projects/{project_id}/imports/pubmed/preview  {pmids[]}
      backend: efetch in batches of 200 (rate ≤ 3 req/s, ≤ 10 with NCBI_API_KEY),
               normalize, classify each record against the project
      ← {new[], exact_duplicates[], probable_duplicates[{record, match, score}], not_found[]}
  → user reviews probable duplicates (keep / merge)
  → POST .../imports/pubmed/confirm  {preview_token, decisions}
      backend: inserts articles, records a screening_run(kind='import')
```

`preview_token` is an HMAC over the normalized records the preview returned
(same idea as the AI-run plan token, ADR 0021), so confirm inserts exactly
what the user saw without the server holding state between the two calls.

### 4.2 Normalization

A new `normalize_pubmed_record` in `services/article_source_normalization.py`
next to `normalize_zotero_item`, reusing `normalize_doi` and `extract_year`.
Fields: title, abstract (structured abstracts joined with their labels),
authors (`Last, Initials`), journal, year/month/day, volume, issue, pages,
doi, pmid, pmcid, mesh_terms, keywords, article_type (first publication
type), language; `ingestion_source = 'pubmed'`; the raw efetch XML fragment
stays in `source_payload` for audit.

### 4.3 Dedup

- **Exact:** same project and same `pmid`, or same normalized `doi` →
  `exact_duplicates`, never inserted.
- **Fuzzy:** 05-03 §8.2 score. Every pair ≥ 0.85 goes to
  `probable_duplicates` for a human to confirm; < 0.85 is new. No fuzzy
  match is removed automatically in v1 (ASySD and Deduklick both keep the
  borderline band for manual review or keep the record when in doubt [6, 7]).
  Compared against the project's existing articles and within the batch.
- New dependency: `rapidfuzz` (pure C extension, wheels for all targets).
- The import run stores counts for PRISMA: `identified`, `duplicates_exact`,
  `duplicates_fuzzy_confirmed`, `inserted`, `not_found`.

### 4.4 Articles write path

There is no article create endpoint today
(`api/v1/endpoints/articles.py` is read-only). Import inserts through a new
`ArticleImportService` (service layer, repository `flush()` only, the
endpoint commits), scoped by `ensure_project_member` + manager role. RIS and
manual entry keep their current path in v1.

## 5. Data model (Alembic `0094_screening_v1`)

All tables: RLS on, member-read policies through the `public.is_project_*`
helpers, writes through the backend role. `text` + `CHECK` for kinds.

```text
screening_configs            one per project (v1: title/abstract only)
  project_id (unique), reviewer_count 1..3, arbitrator_id, blind_mode,
  ai_enabled, ai_calibration_required (default true),
  calibration_run_id → screening_runs (nullable), created_by, timestamps

screening_assignments        an article enrolled in screening
  project_id, article_id, phase ('title_abstract'), enrolled_at,
  in_calibration_sample bool
  UNIQUE (project_id, article_id, phase)

screening_decisions          one per (assignment, reviewer); append-only history via version
  assignment_id, reviewer_id, decision ('include'|'exclude'|'maybe'),
  exclusion_reason text (one of the protocol's exclusion strings, snapshotted),
  rationale, ai_suggestion_id → screening_ai_suggestions (nullable),
  ai_visible_at_decision bool, version, timestamps
  UNIQUE (assignment_id, reviewer_id)

screening_outcomes           the published result; one per assignment
  assignment_id (unique), decision, exclusion_reason,
  source ('solo'|'consensus'|'arbitrated'),
  arbitrator_id, selected_decision_id, rationale, decided_at, version

screening_ai_suggestions     append-only; one row per model answer
  assignment_id, run_id → screening_runs,
  suggestion ('include'|'exclude'|'maybe'), confidence (0..1),
  criteria jsonb  [{key, kind, text, verdict ('met'|'not_met'|'unclear'),
                    quote, quote_verified}],
  input_fingerprint (sha256 of the exact title+abstract+review question sent),
  protocol_revision, provenance jsonb (engine, key_scope, prompt name/version,
  usage — same shape as build_run_provenance), created_at

screening_runs               import, AI pre-screen and calibration jobs
  project_id, kind ('import'|'ai_prescreen'|'calibration'),
  status ('pending'|'running'|'completed'|'failed'|'cancelled'),
  parameters jsonb, results jsonb, error_message, created_by, timestamps

articles.screening_status    text NULL, kept by a trigger on screening_outcomes
                             and screening_assignments (05-03 §4.4 semantics,
                             title/abstract values only)
ai_usage_ledger.pass_kind    CHECK widened with 'screen'
```

`criteria[].key` is a stable hash of (source slot, kind, text), so a
criterion keeps its key across runs while its text is unchanged, and a
suggestion made under an older protocol is recognizable as such
(`protocol_revision` differs from the project's current one).

## 6. AI pre-screen

### 6.1 One call per article

- Engine and credentials exactly as extraction: `resolve_engine` →
  `resolve_engine_credentials` → `build_model` →
  `metered(extract_structured, LedgerSink(...), ctx)` with a new prompt
  `screening_title_abstract` registered in `llm/pass_kinds.py` as `'screen'`.
- Input: the rendered review question (`render_review_question`, so the
  model sees the same criteria the reviewers configured), the numbered
  criteria list, title and abstract. Nothing else (no journal, no authors:
  less to anchor on, and the fingerprint stays about content).
- Output (pydantic): per criterion `{key, verdict, quote}`, overall
  `{suggestion, confidence, one_sentence_reason}`.
- **Quote check:** `quote_verified` is true only when the quote is a
  whitespace-normalized substring of the title or abstract that was sent. An
  unverified quote is shown with a "verify manually" badge, as extraction
  does for ungroundable values.
- **Decision rule for the suggestion (author's call, recall-first):** the
  model's overall suggestion is stored as is; the UI surfaces `exclude` only
  when every inclusion criterion is `not_met` or some exclusion criterion is
  `met` with a verified quote. Anything else is shown as `maybe`. The stored
  row keeps both, so the rule can be audited and changed.
- No abstract → no AI call; the article is flagged `no_abstract` and goes to
  humans.

### 6.2 Batches

A pre-screen run over N assignments follows the extraction batch shape
(`ExtractionBatchService.start`: engine precheck → queue probe → flush-only
create; endpoint commits; `kick_batch`), but on `screening_runs`, because
extraction batches are template-bound (`models/extraction_batch.py:41`).
One Celery task per article, re-advancing the run on completion. Frontend
polls only while a run is active, mirroring `useExtractionBatches`.

### 6.3 Calibration gate

1. Manager sets the sample size (default 150, author's call) and starts
   calibration. prumo draws a seeded random sample of assignments (seed
   stored in the run) and marks `in_calibration_sample`.
2. Reviewers screen the sample with AI hidden (`ai_visible_at_decision =
   false` is enforced, not just defaulted).
3. AI pre-screens the same sample in the background.
4. When every sampled assignment has an outcome, the calibration run
   computes, against the human outcome (include+maybe = positive):
   recall, specificity, the number of human includes the AI would have
   surfaced as `exclude`, and the list of disagreements with both sides'
   reasons. Stored in `screening_runs.results`.
5. The manager sees the report and enables AI for the rest. While
   `ai_calibration_required` is true and no completed calibration exists,
   `POST .../ai-prescreen` answers 409 `CALIBRATION_REQUIRED`.

prumo reports the numbers; it does not decide a threshold. The report shows
the recall with its 95% Wilson interval and the number of human includes it
rests on, because 150 records with ~10 includes make a point estimate
misleading; the manager can extend the sample (same seed, more records)
before deciding. For scale: pooled LLM sensitivity in a 2025 meta-analysis
was 0.812 (95% CI 0.617–0.920) with very high heterogeneity [3], and a 2025
review found the best approaches near 95–97% recall, none consistently at
the 99% its authors consider necessary to replace a human [4]. The gate
exists because a given review cannot assume the good end of that range.

**Revalidation (author's call).** A calibration is tied to the engine,
prompt version and `protocol_revision` it ran under. If any of the three
changes, the gate closes again until a new calibration completes, since a
model change is reported to shift recall [5].

## 7. Human review

- Queue: one article at a time, title + abstract with criterion terms
  highlighted, AI panel (suggestion, per-criterion verdicts, quotes) when AI
  is visible, keys `1` include / `2` exclude / `3` maybe / `e` exclude with
  reason (reasons = the protocol's exclusion strings, numbered).
- Solo: the decision publishes an outcome (`source = 'solo'`).
- Dual: an outcome publishes when all `reviewer_count` decisions agree
  (`consensus`); any disagreement sends the assignment to the arbitrator's
  conflicts list, who adopts one decision or overrides with a rationale
  (`arbitrated`). Conflict detection reads decisions ordered by
  `(created_at, id)` (05-03 §12.3).
- Blind mode hides other reviewers' decisions until the outcome publishes;
  reuse the reveal truth table idea of ADR 0012, not its tables.
- Editing a decision after an outcome reopens the assignment only if the
  outcome was `solo`; otherwise it goes through the arbitrator.

## 8. PRISMA counts (v1)

Read-only service over `screening_runs(kind='import')` and outcomes:
records identified (by source), duplicates removed (exact + fuzzy),
records screened, records excluded at title/abstract (with reason counts),
records sought for retrieval (included + maybe). Shown on the `prisma` tab
as numbers; the diagram itself is v2.

**AI-use statement.** The same tab renders a copyable methods paragraph
built only from stored rows: engine and model, prompt name and version,
dates of use, purpose (pre-screen suggestion, never applied without a human
decision), number of reviewers per record and how conflicts were resolved,
and the calibration figures (sample size, human includes, recall and
specificity with intervals). This is what the Cochrane/Campbell/JBI/CEE
position statement asks authors to report [1] and what the proposed
PRISMA-trAIce items on human oversight and performance cover [2].

## 9. API (all under `/api/v1/screening`, `ApiResponse` envelope)

```
GET    /projects/{id}/config                     member
PUT    /projects/{id}/config                     manager
POST   /projects/{id}/imports/pubmed/preview     manager
POST   /projects/{id}/imports/pubmed/confirm     manager
POST   /projects/{id}/enroll                     manager  (all unenrolled, or ids)
GET    /projects/{id}/queue?cursor=              member   (next assignments for me)
GET    /assignments/{id}                         member   (blind-aware)
PUT    /assignments/{id}/decision                member   (If-Match: version)
GET    /projects/{id}/conflicts                  arbitrator/manager
POST   /assignments/{id}/arbitrate               arbitrator
POST   /projects/{id}/calibration                manager  (start; sample size)
GET    /projects/{id}/calibration                member   (report)
POST   /projects/{id}/ai-prescreen               manager  (409 CALIBRATION_REQUIRED)
GET    /runs/{id}                                member
POST   /runs/{id}/cancel                         manager
GET    /projects/{id}/prisma                     member
```

Every route binds the project through the existing guards
(`api/deps/security.py` helpers; `assignment` and `run` get one owned-guard
each, listed in `.claude/rules/backend.md` § Ownership guards).

## 10. Frontend

- `screening` and `prisma` tabs lose `comingSoon`.
- Screening tab states: not configured → configure (reviewers, blind, AI) ·
  nothing imported → "Import from PubMed" · calibration in progress ·
  queue · conflicts (arbitrator) · done.
- Import dialog: drop the PubMed CSV or paste PMIDs → preview table with the
  three buckets → probable-duplicate pairs side by side → confirm.
- Copy in `frontend/lib/copy/screening.ts`; hooks under
  `frontend/hooks/screening/`; services in `frontend/services/screeningService.ts`;
  every read through the API (no direct Supabase query).

## 11. Delivery as stacked PRs

1. `docs(specs)`: this document.
2. `feat(imports)`: PubMed efetch, normalization, dedup, preview/confirm,
   import run. Usable on its own (articles land deduplicated).
3. `feat(screening)`: migration, config, enroll, queue, decisions, outcomes,
   conflicts, trigger, Screening tab without AI.
4. `feat(screening)`: AI pre-screen prompt, ledger kind, runs, AI panel.
5. `feat(screening)`: calibration sample, report, gate; PRISMA counts.

## 12. Tests

- Unit: PubMed XML → normalized record (fixtures from real efetch responses
  saved under `backend/tests/fixtures/pubmed/`), dedup scores at the
  thresholds, quote verification, the suggestion display rule, Wilson
  interval, criterion keys stable across runs.
- Integration (real local Supabase): import confirm inserts exactly the
  previewed set; exact duplicates never insert; solo/dual/3-reviewer
  outcomes; deterministic conflicts regardless of insert order; blind
  masking; `screening_status` trigger; `CALIBRATION_REQUIRED`; a suggestion
  row carries fingerprint, protocol revision and provenance; ledger row with
  `pass_kind = 'screen'`; RLS isolation between projects.
- The 05-03 §12.3 PR #7 regression list applies in full.
- Frontend: vitest for the queue hook (optimistic advance, rollback on 409),
  keyboard map, import preview buckets. One Playwright flow: import fixture
  CSV → enroll → decide → PRISMA count.
- End to end on the real dataset: the 1,976-record MIMIC-IV export through
  import and calibration, numbers reported in the PR that ships §6.3.

## 13. Open questions for the maintainer

1. Is `rapidfuzz` acceptable as a dependency, or should fuzzy dedup use
   `pg_trgm` in Postgres instead?
2. Should the import endpoint also replace the RIS dialog's direct insert in
   PR 2, or stay PubMed-only until v2?
3. NCBI asks for `tool` and `email` on E-utilities calls: a new
   `NCBI_EMAIL` / optional `NCBI_API_KEY` setting, or reuse an existing
   contact setting?
4. Calibration default of 150 and the recall-first display rule (§6.1) are
   the proposer's calls; change them here before PR 4.

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
6. Hair K, Bahor Z, Macleod M, Liao J, Sena ES. The Automated Systematic
   Search Deduplicator (ASySD). *BMC Biol* 2023;21:189.
   doi:10.1186/s12915-023-01686-z — exact-field blocking, then similarity;
   borderline pairs go to manual review.
7. Borissov N, Haas Q, Minder B, et al. Reducing systematic review burden
   using Deduklick. *Syst Rev* 2022;11:172. doi:10.1186/s13643-022-02045-9 —
   normalized metadata and rules; conservative, keeps the record when in
   doubt.
