# Fork vs upstream: review-ai-hub compared with prumo

- **Date:** 2026-09-26
- **Fork:** `fabianofilho/review-ai-hub`, branch `dev` at `14703e7` (2026-09-25)
- **Upstream:** `raphaelfh/prumo` (the repository formerly named `raphaelfh/review-ai-hub`), branch `dev` at `cea4c26` (2026-09-26)
- **Fork point:** `997cbd9` (2026-03-29), the last upstream commit in the fork
- **Findings covered:** TOPO-09, REV-07, REV-09, REV-11, INTEG-13, INTEG-12, HUB-17 (and REV-10, REV-16 as items to send upstream), from the lab's review of its DataSUS and systematic review repositories (September 2026)

This report supports one decision: archive the fork and use the upstream, reopen the contribution upstream (PR #7 was not merged), or keep a hard fork and take on the AGPL obligations. It changes no code.

## Summary

| Area | Fork (`14703e7`) | Upstream (`cea4c26`) |
|---|---|---|
| Title/abstract and full-text screening | Yes, backend and UI, with defects | No. The tab shows "coming soon". Designed in a spec, not implemented |
| PRISMA 2020 counts | Yes, but counts decision rows, not articles [REV-07] | No. The tab shows "coming soon" |
| Import from Zotero | Yes (from before the fork) | Yes, evolved |
| Import from RIS | Yes, parsed in the browser, no dedup | Same code path |
| Import from Scopus CSV | Yes, dedup by DOI or URL | No (designed for v1 of screening) |
| Import from PDF with AI metadata | Yes | No (deferred to the AI phase) |
| CHARMS extraction input | First 15,000 characters of the PDF text, nothing recorded [REV-09] | Whole stored text up to a 96,000-token budget, lowest-priority sections dropped first, truncation recorded and shown |
| PROBAST | 20 signaling questions only, no domain judgment, no applicability, no overall [REV-11] | PROBAST 2019 with per-domain risk of bias, applicability and overall fields; PROBAST+AI 2.2.0 with computed overall; QUADAS-2 |
| Multi-reviewer consensus | Screening: conflict from the first two decisions. Extraction and assessment: other reviewers' values shown side by side with an agreement badge, but no consensus rule or arbitrator, and the `is_consensus` flag is never set | Extraction and quality assessment: reviewer count, consensus rule, arbitrator |
| Machine access | Supabase user JWT only; export of article metadata only [INTEG-13] | Personal access tokens and an MCP server at `/mcp` with 11 tools; Excel export of extraction and quality assessment |
| Deploy config | Render web service and Vercel, no Celery worker | Railway web service, Celery worker and Redis, Vercel frontend |

In short: the upstream already solved REV-09, REV-11 and INTEG-13, in an architecture the fork cannot merge. The fork's only real functional advantage is screening, PRISMA and two import paths. That screening code is the part the upstream rejected, and REV-07 sits inside it.

**Correction to TOPO-09.** The lab's review states that the upstream later implemented screening and import on its own (TOPO-09), and its decision 9 asks to archive the fork if those cover the lab's case. At `cea4c26` there is nothing to cover it: the upstream has no screening code, no PRISMA and no import source beyond Zotero, RIS and manual entry (section 2). Its own spec and roadmap say so. TOPO-09 also said the lab's contributions were never sent upstream; they were, as PRs #7 and #37 (section 8). Archiving the fork therefore means giving up in-app screening, not moving to an upstream version of it.

## 1. How this was measured

- Code was read on both sides. Paths are relative to each repository root, prefixed `fork:` or `upstream:`. Line numbers refer to the SHAs above.
- The local upstream clone is shallow (depth 1). To count commits, a metadata-only bare clone of the upstream was made outside the repository (`git clone --bare --filter=tree:0`). PR heads were fetched from `refs/pull/*`. The fork clone has enough history (102 commits) to reach the fork point.
- The GitHub API for the upstream repository was not available in this session. The state of upstream PRs is inferred from git refs and from the upstream's own `docs/ROADMAP.md`.
- Every file:line citation was checked a second time, in a separate pass, against both trees at the SHAs above. File and line counts in section 8 were recomputed from the git objects of both clones.
- No deployed instance of either side was accessed. Whether the fork is deployed today was not verified.

## 2. Screening and import

### What the upstream has

- **No screening.** The sidebar marks screening and the PRISMA report as `comingSoon` (upstream: `frontend/components/layout/sidebarConfig.ts:54`, `:57`), and the project view renders a placeholder for both (upstream: `frontend/pages/ProjectView.tsx:250-254`).
- **Screening is designed, not built.** `docs/ROADMAP.md:36-45` lists "Screening workflow + imports" under "Future cycles, designed, not started" and says nothing is implemented, verified on 2026-08-30 against production. The design is `docs/superpowers/specs/2026-05-03-screening-and-imports-design.md`, whose header (`:8-19`) repeats that nothing is built.
- **Imports that exist:** Zotero (upstream: `backend/app/api/v1/endpoints/zotero_import.py:90`, `backend/app/services/zotero_import_service.py`), RIS parsed in the browser and inserted straight into Supabase without dedup (upstream: `frontend/components/articles/RISImportDialog.tsx:88-90`, `frontend/lib/risParser.ts`), manual entry (upstream: `frontend/components/articles/ArticleForm.tsx`), and attaching a PDF to an existing article, parsed at ingest (upstream: `backend/app/api/v1/endpoints/article_files.py:39`, `backend/app/services/article_file_ingest_service.py:1-8`). The project view wires only the Zotero and RIS dialogs (upstream: `frontend/pages/ProjectView.tsx:12-13`).
- **Imports planned for screening v1** (spec `:584-594`): Scopus and Web of Science CSV, PubMed query, RIS through a unified menu, PDF with manual metadata, fuzzy dedup on title, first author and year (`:596-615`), and Unpaywall full text (`:617-623`). PDF metadata extraction by AI is explicitly deferred (`:625-631`).

### What only the fork has

- **Screening backend:** 13 routes under `/screening` (fork: `backend/app/api/v1/endpoints/screening.py:48-464`): configuration, decisions, progress, conflicts and resolution, AI screening of one article or a batch, PRISMA, dashboard, bulk decisions and advance to full text. Services in `fork: backend/app/services/screening_service.py` and `ai_screening_service.py:95`, `:153`; tables in `fork: backend/alembic/versions/20260329_007_add_screening_tables.py`.
- **Screening UI:** `fork: frontend/components/screening/` (card view, configuration editor, dashboard with PRISMA and Cohen's kappa), wired at `fork: frontend/pages/ProjectView.tsx:285-286`.
- **Scopus CSV import:** `fork: backend/app/api/v1/endpoints/article_import.py:216-217`, `backend/app/services/article_import_service.py:82`, with normalization in `backend/app/services/article_source_normalization.py:180`. Dedup matches Zotero key, DOI or landing URL and, on a match, overwrites the stored fields with the new row (fork: `backend/app/repositories/article_repository.py:215-242`, overwrite at `:228-234`).
- **PDF import with AI metadata:** `fork: backend/app/api/v1/endpoints/article_import.py:48-49` and `:137-138`, `backend/app/services/pdf_metadata_extraction_service.py:104-115`.
- **Canonical normalizers** for RIS, manual entry, Scopus and PDF (fork: `backend/app/services/article_source_normalization.py:115`, `:150`, `:180`, `:257`). The upstream module has only the Zotero one (upstream: `backend/app/services/article_source_normalization.py:59`). The fork's RIS and manual normalizers are not called anywhere: RIS still goes through the browser path, the same as upstream (fork: `frontend/components/articles/RISImportDialog.tsx:87-89`).

### Assessment

The upstream spec records why PR #7 was not merged (spec `:26`, `:32`). PR #7 predates the upstream database refactor. The spec also lists concrete defects: denormalized `screening_phase` semantics, nondeterministic and racy conflict logic, no rollback on exception, the frontend querying Supabase directly, a CSV preview parser that breaks on escaped quotes, and a cascade that could corrupt extraction data. Several are still visible in the fork today:

- conflicts compare `decisions[0]` and `decisions[1]` from a query with no `ORDER BY` (fork: `backend/app/services/screening_service.py:151`, `backend/app/repositories/screening_repository.py:50-62`);
- the card view reads articles straight from Supabase (fork: `frontend/components/screening/ScreeningCardView.tsx:52-56`);
- the CSV preview splits lines on commas (fork: `frontend/components/articles/CSVImportDialog.tsx:74-79`).

The spec's section 12.3 (`:776-785`) turns most of those defects into regression tests that any future screening PR must pass: rollback, deterministic conflicts, three or more reviewers, concurrent decisions, `screening_status` semantics, the `ai_suggestions` cascade and the CSV parser. The frontend bypass is not among them; the spec instead gives every screening read its own `/api/v1/screening` endpoint (spec `:354-416`).

The spec was also written against the lab's work. Its header names the branch `fork/fabianofilho/dev` (spec `:24`) and keeps only the frontend UI sketches from PR #7 (spec `:26`), which the lab then sent as PR #37 on 2026-05-03 (section 8). The upstream maintainer engaged with the contribution and redesigned it, which matters for scenario B.

## 3. PRISMA counts and conflict resolution [REV-07]

**Fork.** REV-07 is confirmed at `14703e7`:

- `get_prisma_counts` fills excluded and included from `count_by_decision` (fork: `backend/app/services/screening_service.py:245-248`), which counts `ScreeningDecision.id` grouped by decision (fork: `backend/app/repositories/screening_repository.py:105`, `:113`). That is rows, not articles.
- The unique key allows one row per reviewer (fork: `backend/alembic/versions/20260329_007_add_screening_tables.py:57`). With dual review, every agreed decision counts twice. At full text, an article in conflict counts once as included and once as excluded. At title and abstract, it counts as excluded even when it moves on to full text.
- `resolve_conflict` stores `resolved_decision` (fork: `screening_service.py:190`), but the PRISMA counts never read it.
- `duplicates_removed` is fixed at 0 (fork: `screening_service.py:243`), although the CSV import computes a duplicate count that is never stored (fork: `article_import_service.py:96-131`).
- One more defect, found while checking this: when a reviewer changes an existing decision, the service returns right after the update (fork: `screening_service.py:109-117`). It skips the conflict check at `:133-134`, so a changed decision never creates or clears a conflict, and it also skips the update of the article's denormalized `screening_phase` at `:137`.
- With a single reviewer (`require_dual_review` false by default, fork: `20260329_007_add_screening_tables.py:29`) include and exclude counts are right; the error appears in dual review.
- Outside screening, the fork has no consensus workflow either. Extraction shows other reviewers' values with an agreement badge (fork: `frontend/components/shared/comparison/ConsensusIndicator.tsx`, `frontend/components/extraction/colaboracao/OtherExtractionsPopover.tsx:95`). The `is_consensus` columns exist (fork: `backend/app/models/extraction.py:468`, `backend/app/models/assessment.py:576`), but no code sets them.

**Upstream.** There is no screening and no PRISMA, so there is nothing to count. The design fixes this class of bug by construction. It has an append-only `screening_outcome` table with one row per assignment, that is per article and phase (spec `:55`, `:58`, `:142-152`, `:177-192`), and a trigger keeps `articles.screening_status` as the single source of truth (spec `:56`, `:266-316`). PRISMA and kappa move to a read-only analytics service (spec `:339`, `:388-390`). For consensus, the upstream already has the mechanism the spec mirrors, in extraction: `reviewer_count`, `consensus_rule` and `arbitrator_id` (upstream: `backend/app/models/extraction_versioning.py:133-140`, rules in `backend/app/models/base.py:54`) and an append-only consensus service with optimistic concurrency (upstream: `backend/app/services/extraction_consensus_service.py:40-49`).

## 4. CHARMS extraction input [REV-09]

**Fork.** REV-09 is confirmed at `14703e7`. The prompt that fills each CHARMS section embeds `pdf_text[:15000]` (fork: `backend/app/services/section_extraction_service.py:756`). The model identification step does the same (fork: `backend/app/services/model_extraction_service.py:299`). `pdf_text` is the full text with page markers (fork: `backend/app/services/pdf_processor.py:84-101`). Nothing logs or stores how much was cut. By contrast, the fork's PROBAST assessment sends the whole PDF as `input_file`. It switches to File Search above 32 MB for a single item (fork: `backend/app/services/ai_assessment_service.py:67-68`, `:195-233`) and above 10 MB in the batch path (`:405`).

**Upstream.** Solved, with a different pipeline:

- `build_prompt_input` uses the stored markdown of the article when it fits the budget. Otherwise it assembles the parsed blocks, dropping whole sections by priority (upstream: `backend/app/services/extraction_prompt_input.py:78-92`). It logs `truncated`, block counts and estimated tokens (`:94-102`) and returns them for provenance (`:103-109`).
- The budget is `LLM_ASSEMBLY_BUDGET_TOKENS = 96_000` (upstream: `backend/app/core/config.py:180`). Tokens are counted with tiktoken for OpenAI models and at 4 characters per token otherwise (upstream: `backend/app/llm/assembler.py:327`, `:330-342`), so the budget is in the order of 380,000 characters, enough for a typical full paper.
- When a paper is over budget, Results rank above Methods and Introduction, and page chrome, appendices and references go first (upstream: `backend/app/llm/assembler.py:106-118`).
- Section extraction uses this path (upstream: `backend/app/services/section_extraction_service.py:263-277`). The review UI warns when the text was cut (upstream: `frontend/components/extraction/ai/shared/GenerationDetailsContent.tsx:206-210`, copy at `frontend/lib/copy/extraction.ts:670`).
- Evidence quotes are anchored back to page and block (upstream: `backend/app/services/evidence_anchor_service.py:1-8`), and values that cannot be anchored get a "Verify manually" badge instead of being rejected (upstream: `frontend/lib/copy/extraction.ts:688`, `:698`; `docs/ROADMAP.md:52`). REV-09 suggested checking that the quoted passage exists in the PDF; the upstream flags it rather than blocking it.
- The model identification step that truncated in the fork was retired upstream in favor of entry groups ("B6 the model pipeline retired (#829)" in upstream `docs/ROADMAP.md:49`; the fork's `model_extraction_service.py` no longer exists upstream).
- Templates: CHARMS (upstream: `backend/app/seed.py:271`) and CHARMS + Multimodal for ML models (upstream: `backend/app/seed.py:186`).

## 5. PROBAST [REV-11]

**Fork.** REV-11 is confirmed at `14703e7`:

- the seed creates PROBAST as 20 signaling questions answered yes, probably yes, probably no, no or no information (fork: `backend/app/seed.py:52`, `:64-193`);
- `aggregation_rules` only lists the four domains (fork: `backend/app/seed.py:81`), and nothing reads it to compute anything;
- there is no item for per-domain risk of bias or applicability;
- `overall_risk_of_bias` exists in the schema (fork: `backend/app/schemas/assessment.py:460`) and `overall_risk` and `applicability` in the frontend types (fork: `frontend/types/assessment.ts:161-163`), but no code fills them;
- there is no PROBAST+AI.

**Upstream.** Solved and extended:

- **PROBAST 2019** is a quality-assessment template with 5 sections. Each domain has signaling questions plus a risk-of-bias judgment, and domains 1 to 3 also have applicability concerns (upstream: `backend/app/seed.py:1450-1483`, `:1491`, domains at `:1566-1757`). The overall section has overall risk of bias and overall applicability (`:1759-1783`). In classic PROBAST these overall fields are not computed. Every judgment field, per domain and overall, carries an LLM instruction (`:1467`, `:1480`, `:1770`, `:1780`), so the AI can propose judgments here and the reviewer accepts, rejects or edits them (reviewer decisions in upstream: `backend/app/models/base.py:57`).
- **PROBAST+AI 2.2.0** (Moons et al., BMJ 2025) is seeded separately. It follows the published form item by item, 13 sections and 95 fields (upstream: `backend/app/seed_probast_ai.py:1-36`, version at `:723`).
  - Domain judgments get a derived default from the signaling questions, and the assessor records the final value.
  - The overall values are computed with the rule "any domain high, overall high" (upstream: `backend/app/seed_probast_ai_data.py:458`, `:464`; `backend/app/services/derived_judgment_service.py:236-247`).
  - Judgments and rationales are excluded from every LLM call, so the AI only answers signaling questions (upstream: `backend/app/seed_probast_ai.py:32-36`).
- **QUADAS-2** is seeded with the same structure (upstream: `backend/app/seed.py:1796`).
- Quality assessments export to Excel from the same dialog as extraction (upstream commit `9b05014`, #788).

This matches the REV-11 suggestion: keep PROBAST 2019 for reviews in progress and seed PROBAST+AI as a separate, versioned instrument. For the lab's ML models, PROBAST+AI is the one that keeps every judgment with the human assessor.

## 6. Machine API [INTEG-13, INTEG-12, HUB-17]

**Fork.**

- Authentication is only the Supabase user JWT (fork: `backend/app/core/deps.py:107`, `backend/app/core/security.py:28`).
- `user_api_keys` stores LLM provider keys, not API tokens (fork: `backend/app/api/v1/endpoints/user_api_keys.py:1-5`).
- The only export is article metadata as CSV, RIS or RDF (fork: `backend/app/api/v1/endpoints/articles_export.py:1-4`, `backend/app/services/articles_export_service.py`).
- There is no MCP server (no `mcp` reference in `backend/app`).

**Upstream.** Yes, it has an MCP server:

- **Personal access tokens:**
  - scope `read` or `read_write`, expiry at most 365 days, only the SHA-256 hash stored, at most 10 active per user (upstream: `backend/app/models/personal_access_token.py:30-47`, `backend/app/services/pat_service.py:53-73`);
  - managed at `/api/v1/me/tokens` (upstream: `backend/app/api/v1/endpoints/personal_access_tokens.py:38-80`, prefix at `backend/app/api/v1/router.py:73-77`) and from a settings card (upstream: `frontend/components/user/PersonalAccessTokensGroup.tsx`, `McpClientConfigCard.tsx`);
  - added on 2026-09-25 (upstream commit `2e35180`, #972).
- **MCP server** at `/mcp`, streamable HTTP, token authenticated, outside the JWT dependency (upstream: `backend/app/main.py:175-186`):
  - one dispatcher checks scope, rate limit, project membership and, for writes, the manager role (upstream: `backend/app/api/mcp/server.py:1-14`, `:219-222`);
  - limits are 120 reads and 20 writes per minute (`:55-56`);
  - read tools: `list_projects`, `get_project`, `list_articles`, `get_article`, `get_article_text`, `get_article_pdf`, `search_project_text`, `get_template`, `get_extractions`;
  - write tools: `update_project_details` and `edit_template_draft` (upstream: `backend/app/api/mcp/tools/`);
  - setup guide for Claude Code and other clients: `docs/how-to/connect-an-ai-agent.md:16-39`, `:117-129`, `:165`;
  - only clients that can send an `Authorization` header are supported (Claude Code, Cursor, VS Code, Gemini CLI, Codex, Windsurf). Web chat connectors such as claude.ai and ChatGPT need OAuth and are not supported (`docs/how-to/connect-an-ai-agent.md:11-14`);
  - an agent cannot write extraction values, start an AI extraction run or upload a PDF (`docs/how-to/connect-an-ai-agent.md:154-161`).
- **Excel exports** of extraction and quality assessment, JWT authenticated (upstream: `backend/app/api/v1/endpoints/extraction_export.py:62`, `:129-130`).

**What this means for the squad (INTEG-12, HUB-17):**

- The `literature-review` pipeline in the ai-lab-hub can read CHARMS extraction and PROBAST results back through `get_extractions`. The tool resolves any project template id without filtering by kind and passes the kind through (upstream: `backend/app/api/mcp/tools/extractions.py:62`, `:71`; `backend/app/services/extraction_agent_read_service.py:552`), so quality-assessment templates appear readable the same way. This was not exercised against a running instance.
- Tokens are per user, not per project as INTEG-13 proposed. To limit an agent to one review, create a dedicated account that is a member of only that project.
- The MCP has no screening data and no tool to create articles. Importing the search results stays a human step in the UI (Zotero or RIS), which can serve as one of the squad's human checkpoints.
- The squad's agents run in Claude Code, which the MCP supports. Whether the hub's desktop app can pass a bearer header to a remote MCP was not checked; a claude.ai connector cannot.
- INTEG-12 proposed that the squad also push the import and read screening decisions and PRISMA from the app. With the upstream, only the read-back half exists: extraction and assessment values, not screening.

## 7. What the fork has that could go upstream

| Item | Where in the fork | Upstream status | Worth offering? |
|---|---|---|---|
| Startup guard against an empty or published `ENCRYPTION_KEY`, and the `.env.example` fix [REV-16] | `backend/app/core/config.py:15-24`, `:118-140`; `backend/app/main.py:68`; `.env.example:35-40` | Upstream still ships the published default (upstream: `backend/app/core/config.py:205`, `backend/.env.example:43`) and derives keys from it without a guard (upstream: `backend/app/core/security.py:370`). Its root `.env.example:47` still documents `ZOTERO_ENCRYPTION_KEY`, which no code reads | Yes. Small, independent, security relevant |
| Scopus CSV normalizer | `backend/app/services/article_source_normalization.py:180-256` | Planned in spec `:584-594` under a new `imports/` module, with papaparse on the frontend | Maybe, as part of the imports module, rewritten to the spec's API and dedup |
| CHARMS template fields specific to endocarditis [REV-10] | Same issue in the fork | Also upstream (upstream: `backend/app/seed.py:602-604`) | Yes, as an issue, not code |
| Screening UI sketches | Branch `frontend/screening-ui-sketches-from-pr7`, commit `234d4fe` | Already proposed as upstream PR #37 (2026-05-03), not in `dev`; the spec designs its own UI (spec `:427-580`) | Already offered |
| Screening backend and PRISMA | See sections 2 and 3 | Rejected design; greenfield spec instead | No, not as is. Implementing the upstream spec is the path (section 10, scenario B) |
| PDF import with AI metadata | See section 2 | Deferred to the AI phase (spec `:625-631`) | Later, if upstream reopens the AI phase |
| Other September 2026 fixes: membership checks, RLS on screening tables, PDF storage key checks, backend CI baseline, tests, strict typing [REV-01, REV-02, REV-03, REV-06, and REV-05 in part] | 43 commits, starting at `d6d8378` | Mostly on endpoints and services the upstream deleted (section 8); the upstream has its own scope layer (upstream: `backend/app/api/deps/scope.py`) and a membership check in its PR template | No. Useful only while the fork lives |

## 8. Distance between fork and upstream

How it was estimated: commit counts come from the metadata-only upstream clone and the fork clone (section 1). File comparisons use `git ls-files` and blob hashes at the two SHAs. Line counts use `wc -l` over tracked files.

**Commits.**

- **Upstream:** 1,030 commits since the fork point (`git rev-list --count 997cbd9..cea4c26`), 987 of them not merges. The upstream maintainer wrote 1,003; dependabot 25, others 2. `dev` has 1,139 commits in total, so the fork point sits at about commit 109.
- **Upstream by month since the fork point (author date):** March 1, April 188, May 280, June 180, July 67, August 165, September 149. The pace has not slowed.
- **Upstream diff since the fork point:** 2,876 files changed, +561,566 and -91,759 lines. In `backend/app` and `frontend` alone: 1,628 files, +213,056 and -72,408.
- **Fork:** 50 commits since the fork point (45 not merges):
  - `43fdc69` and `68397ea` (March and April 2026) are the lab's feature work, 5,228 added lines in 39 files. That is the "5,228-line change" the upstream spec rejects.
  - 43 commits from September 2026 (security fixes, CI baseline, tests, typing).
  - In total: 182 files changed, +20,767 and -3,761.

**PRs sent upstream.**

- PR #7 head is `a16b581`, the fork's merge of `43fdc69` and `68397ea`. Those commits are in neither upstream `dev` nor `main`, and the upstream roadmap calls it "the closed PR #7" (upstream: `docs/ROADMAP.md:44`).
- PR #37 head is `234d4fe` (screening UI sketches, 2026-05-03), branched from upstream `dev` at `cace104` (2026-05-01). It is not in `dev` or `main`.
- `git ls-remote` on the upstream lists `refs/pull/7/head` and `refs/pull/37/head` but no `refs/pull/*/merge` for either, so neither is an open, mergeable PR.
- The fork's `fix/ci-secrets-in-job-level-if` (`7d0c564`) is not an upstream object.

**Structure.**

- **Tracked files:** 766 in the fork, 2,607 upstream. They share 341 paths, and only 50 of those are byte-identical. There are 425 fork-only paths and 2,266 upstream-only paths.
- **Code size:** Python in `backend/app` is 25,377 lines in the fork and 59,160 upstream. TypeScript in `frontend`, without `*.test.*` files, is about 79,000 and 100,000. Files under `backend/tests`: 59 in the fork, 509 upstream.
- **Merge surface:** the fork modified 123 files that existed at the fork point. Since then, the upstream has changed 85 of them in place, moved 3 (the first migrations, into `versions/archive/`, with edits) and deleted the other 35. None is untouched. The deleted files include the modules the fork's work sits on:
  - endpoints `ai_assessment.py`, `model_extraction.py`, `project_assessment_instruments.py`, `user_api_keys.py`;
  - models `assessment.py`, `user_api_key.py`;
  - services `ai_assessment_service.py`, `model_extraction_service.py`, `project_assessment_instrument_service.py`, `api_key_service.py`, `openai_service.py`, `pdf_processor.py`.
- **Database:**
  - The upstream squashed its first 18 migrations into `0001_baseline_v1` (upstream: `backend/alembic/versions/0001_baseline_v1.py:1-24`, originals in `versions/archive/`) and has since reached `0080`. Along the way it dropped the legacy assessment stack (`archive/20260426_0009_drop_legacy_assessment_stack.py`) and `ai_suggestions` (`archive/20260428_0019_drop_ai_suggestions.py`).
  - The fork's chain ends at `20260924_010`, and its screening table still has a foreign key to `ai_suggestions` (fork: `backend/alembic/versions/20260329_007_add_screening_tables.py:53`).
  - A fork database cannot be upgraded to the upstream head. Moving data means export and re-import.
- **Identity:** the upstream renamed itself to prumo, and its copyright line now reads "Prumo contributors" (upstream: `COPYRIGHT.txt`). The fork keeps "Review AI Hub contributors" (fork: `COPYRIGHT.txt`). The upstream also moved its backend from Render to Railway, with a worker and Redis (upstream: `railway.toml:76-92`). The fork still deploys to Render without a worker (fork: `render.yaml`).

Conclusion: rebasing or merging is not a realistic option. Anything that goes upstream has to be rewritten against the current upstream code.

## 9. AGPL obligations if the lab keeps a hard fork with a deploy

Both sides are `AGPL-3.0-only` (fork: `LICENSE`, `LICENSE.txt`, `COPYRIGHT.txt`; upstream: `LICENSE`, `COPYRIGHT.txt`). This is a reading of the license text, not legal advice. If the deploy serves people outside the lab or holds third-party data, ask the university's legal office.

1. **Source for network users (section 13).** Anyone who uses a modified version over a network, lab members included, must be offered the Corresponding Source of the exact running version, free of charge, from a network server. In practice, add a visible link in the app (footer or About) to the public repository at the deployed commit. The fork frontend has no such link today (no match for AGPL, "source code" or a repository URL in `frontend/`).
2. **Corresponding Source is the whole running system (section 1).** That covers the build and deploy files needed to run it: `render.yaml`, `vercel.json`, Dockerfile, migrations and seed. Secrets are not part of it. Deploy only from commits pushed to the public repository, and tag each deploy.
3. **Modification notices (section 5a).** Modified files must say they were changed, and when. A "Modifications" section in the README listing what the lab changed since `997cbd9`, with dates, plus the git history, covers this.
4. **Keep notices, add yours (sections 4 and 5).**
   - Keep `LICENSE` and the existing copyright line.
   - Add one for the lab's contributions.
   - The whole work stays AGPL-3.0-only. The lab's default license (MIT, LABDAPS) does not apply to this repository. Lab-authored files can also be offered under another license elsewhere, but not inside this combined work.
5. **No extra restrictions (section 7), and termination on violation (section 8).** Rights are restored if a violation is fixed within 30 days of the first notice.
6. **Do not present the fork as the upstream.** This is not a license clause. Section 7(f) lets licensors decline trademark rights, 7(c) lets them forbid misrepresenting the origin of their material, and 7(d) lets them require modified versions to be marked as different from the original (fork: `LICENSE:316-360`). The upstream `LICENSE` adds none of these terms (it is byte-identical to the fork's), but trademark law applies anyway, and the upstream now brands itself as Prumo. The fork should carry its own name in the deployed UI and README. Several fork files still send people upstream:
   - `README.md:38` and `:75` tell readers to clone `raphaelfh/review-hub-fastapi`;
   - `SECURITY.md:10` and `CODE_OF_CONDUCT.md:63` send vulnerability reports to the upstream.
7. **The CLA only matters if the lab contributes.** At the fork point, the upstream shipped `docs/legal/CLA.md`, still present in the fork. It grants the maintainer a perpetual right to sublicense contributions, including under proprietary licenses (fork: `docs/legal/CLA.md`, sections 1 and 4). It does not bind the lab's own fork. The upstream tree at `cea4c26` has no CLA file (`docs/legal/` is gone) and nothing in `.github/` mentions one. The only trace is an archived plan whose task asked the maintainer to either move the CLA to `.github/CLA.md` or delete it (upstream: `docs/superpowers/plans/archive/2026-06-10-shipped-sweep/2026-05-24-documentation-overhaul-2026.md:803-816`); neither file exists, which points to deletion. Still ask before contributing (scenario B).

## 10. Recommendation: three scenarios and their cost

Effort sizes are estimates, not measurements.

### A. Archive the fork and use the upstream

- **What the lab gets.**
  - REV-09 and REV-11 solved, with PROBAST+AI for ML models.
  - Consensus with an arbitrator for extraction and assessment.
  - Excel exports.
  - A token-authenticated MCP that the squad can read from (INTEG-13), without building an API.
- **What the lab loses.** In-app screening and PRISMA, Scopus CSV import and PDF import with AI metadata.
- **Workaround.** Screen in another tool, then import the included set into prumo by Zotero or RIS. That is the path the upstream design assumes (spec `:48`: "users can import curated sets and skip to extraction"). PRISMA numbers then come from the screening tool, and REV-07 becomes a requirement for that tool: count distinct articles by final decision.
- **One-time cost: small.**
  - README pointing to the upstream (the lab rule is README before archiving), then archive.
  - Take the fork deploy down, if there is one.
  - If the deploy holds real reviews, migrating is a medium task. Articles move via RIS or Zotero. Extraction and assessment values have no importer and the schemas differ, so they need a one-off script or re-entry.
- **Running cost.** Either the upstream's hosted app (`https://prumoai.vercel.app`, where a third party holds the review data; check its terms), or self-hosting an unmodified upstream (Supabase, Railway or Render with a Celery worker and Redis, Vercel). Running it unmodified adds no section 13 duty beyond keeping the license, but linking to the source is still good practice.
- **Risk.** One maintainer writes almost all upstream commits (1,003 of the 1,030 since the fork point), the roadmap is outside the lab's control, and there is no date for screening.

### B. Reopen the contribution upstream

- **PR #7 cannot be revived.** Its design was rejected (spec `:32`), every pre-existing file it touched has changed or disappeared upstream, and the migration chains are incompatible (section 8).
- **Realistic path: implement the upstream's own screening spec (phase alpha)**, in upstream conventions (English, Conventional Commits, tests, the membership checklist in the upstream PR template). Agree the scope first in an upstream issue.
- **Why it may be welcome.** The upstream maintainer wrote the screening spec against the lab's fork and kept the lab's UI sketches (section 2). Screening is on the roadmap as designed and not started (upstream: `docs/ROADMAP.md:36-45`), so an offer to build it is an offer of labor on a designed item, not a new design.
- **Size.** The spec has 9 new tables (8 for screening plus an AI usage log, spec `:100-236`), 7 services in v1 (`:331-347`), 37 endpoints (`:354-416`), a keyboard-driven UI, fuzzy dedup, PubMed and Unpaywall, plus the PR #7 regression suite. The lab's narrower first attempt was 5,228 lines. Expect several person-weeks, plus upstream review time.
- **Small contributions available now (days):** the `ENCRYPTION_KEY` guard with the `.env.example` fix, and an issue about the endocarditis fields in the global CHARMS template (section 7).
- **Cost:** medium to large, and the upstream may decline again. Clear up the CLA question first (section 9, item 7).
- **Benefit:** screening maintained upstream, in the same tool as extraction and PROBAST, with no fork to carry.

### C. Hard fork, with the AGPL obligations

- **Work.**
  - In the fork, fix REV-07, REV-09 and REV-11 (size M each in the review) and INTEG-13 (size G).
  - Also fix the smaller findings still open in the fork: REV-04, REV-08, REV-10, REV-14, REV-15 and REV-17 (size P each). REV-06 (stale tests) is already fixed by the September commits. REV-05 is fixed only on the backend: the frontend lint step still ends in `|| true` and there is no `uv.lock` (fork: `.github/workflows/ci.yml:166`, `:34`).
  - Maintain security alone.
  - Much of this rebuilds what the upstream already has, in an architecture the fork can no longer take fixes from: only 50 of 341 shared paths are identical, the migrations were squashed, and the base modules were deleted.
- **AGPL compliance (section 9):** source link in the UI, modification notice, README and SECURITY rewritten, own name, tagged deploys. Small once, plus discipline on every deploy.
- **Running cost: large and permanent.** The lab owns about 25,000 lines of Python and 79,000 lines of TypeScript, their dependency updates (the upstream took 25 dependabot bumps in six months), Supabase migrations and security fixes.
- **When it makes sense:** only if in-app screening in the lab's own workflow is essential now and the upstream will not take it.

### Recommendation

Scenario A, plus the small part of B:

1. Use upstream prumo for CHARMS extraction and for PROBAST and PROBAST+AI. Point the squad's literature-review integration (INTEG-12, HUB-17, Wave 3 item 4) at the upstream MCP, not at an API built in the fork.
2. Screen outside prumo until the upstream ships screening, and take the PRISMA numbers from that tool.
3. Send upstream the `ENCRYPTION_KEY` guard and the REV-10 issue.
4. Offer to implement the upstream screening spec only if the lab needs in-app screening. Open an issue first.
5. Check whether the fork is deployed and holds data. Export it if so, update the README to point upstream, and archive.

What would change this: the lab's reviews need in-app dual screening now and cannot use an external tool, or the fork deploy holds data that cannot be migrated at an acceptable cost.

## 11. Not verified

- Whether the fork is deployed (Render, Vercel) and whether it holds real review data.
- The GitHub-side state of upstream PRs #7 and #37 (API not available in this session; a second attempt during verification was also refused). PR #7's closure comes from the upstream roadmap; for both, the refs show only that neither is open and mergeable.
- Whether the ai-lab-hub desktop app can connect to a remote MCP with a bearer header.
- Whether the upstream still requires a CLA through a bot on PRs.
- The upstream MCP and exports were read, not run.
- The terms of use and data location of the upstream's hosted app.
