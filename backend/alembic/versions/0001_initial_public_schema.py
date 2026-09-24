"""Initial public schema.

Consolidates all application Supabase migrations (0001–20260219000001) into the
single source of truth for the public schema. auth.* and storage.* objects remain
managed by Supabase CLI (see supabase/migrations/0001_storage_bucket_articles.sql
and supabase/migrations/0002_handle_new_user_trigger.sql).

Revision ID: 0001
Revises:
Create Date: 2026-02-27 00:00:00.000000
"""

import re
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_sql(sql: str) -> list[str]:
    """Split a SQL string on statement-ending semicolons, respecting dollar-quoted blocks.

    asyncpg raises "cannot insert multiple commands into a prepared statement" when
    given multi-statement SQL.  Dollar-quoted strings ($$…$$ or $tag$…$tag$) may
    contain semicolons that must NOT be treated as statement boundaries.
    """
    stmts: list[str] = []
    current: list[str] = []
    in_dollar_quote = False
    dollar_tag: str | None = None
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "$":
            # Scan forward to find a possible closing $ for a dollar-quote tag.
            j = sql.find("$", i + 1)
            if j != -1:
                tag = sql[i : j + 1]
                if re.match(r"^\$[a-zA-Z0-9_]*\$$", tag):
                    if not in_dollar_quote:
                        # Opening tag
                        in_dollar_quote = True
                        dollar_tag = tag
                        current.append(tag)
                        i = j + 1
                        continue
                    elif tag == dollar_tag:
                        # Closing tag
                        in_dollar_quote = False
                        dollar_tag = None
                        current.append(tag)
                        i = j + 1
                        continue
        if not in_dollar_quote and ch == ";":
            stmts.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        stmts.append(tail)
    return stmts


def _exec(sql: str) -> None:
    """Execute a SQL block, splitting on statement boundaries for asyncpg compatibility."""
    for stmt in _split_sql(sql):
        stmt = stmt.strip()
        if stmt:
            op.execute(stmt)


# ===========================================================================
# UPGRADE
# ===========================================================================


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. EXTENSIONS
    # -----------------------------------------------------------------------
    _exec('CREATE EXTENSION IF NOT EXISTS "pgcrypto" SCHEMA public;')
    _exec('CREATE EXTENSION IF NOT EXISTS "pg_trgm" SCHEMA public;')
    _exec('CREATE EXTENSION IF NOT EXISTS "btree_gin" SCHEMA public;')

    # -----------------------------------------------------------------------
    # 2. ENUM TYPES  (final state – includes all incremental additions)
    # -----------------------------------------------------------------------
    _exec("""
        CREATE TYPE review_type AS ENUM (
            'interventional', 'predictive_model', 'diagnostic',
            'prognostic', 'qualitative', 'other'
        );
    """)
    _exec("""
        CREATE TYPE project_member_role AS ENUM (
            'manager', 'reviewer', 'viewer', 'consensus'
        );
    """)
    _exec("""
        CREATE TYPE file_role AS ENUM (
            'MAIN', 'SUPPLEMENT', 'PROTOCOL', 'DATASET',
            'APPENDIX', 'FIGURE', 'OTHER'
        );
    """)
    _exec("""
        CREATE TYPE extraction_framework AS ENUM (
            'CHARMS', 'PICOS', 'CUSTOM'
        );
    """)
    _exec("""
        CREATE TYPE extraction_field_type AS ENUM (
            'text', 'number', 'date', 'select', 'multiselect', 'boolean'
        );
    """)
    _exec("""
        CREATE TYPE extraction_cardinality AS ENUM ('one', 'many');
    """)
    _exec("""
        CREATE TYPE extraction_source AS ENUM ('human', 'ai', 'rule');
    """)
    _exec("""
        CREATE TYPE extraction_run_stage AS ENUM (
            'data_suggest', 'parsing', 'validation', 'consensus'
        );
    """)
    _exec("""
        CREATE TYPE extraction_run_status AS ENUM (
            'pending', 'running', 'completed', 'failed'
        );
    """)
    _exec("""
        CREATE TYPE suggestion_status AS ENUM (
            'pending', 'accepted', 'rejected'
        );
    """)
    _exec("""
        CREATE TYPE assessment_status AS ENUM (
            'in_progress', 'submitted', 'locked', 'archived'
        );
    """)
    # Added in migration 0030_assessment_restructure
    _exec("""
        CREATE TYPE assessment_source AS ENUM ('human', 'ai', 'consensus');
    """)
    # Added in migration 20251215_add_unique_constraints_and_indexes
    _exec("""
        CREATE TYPE extraction_instance_status AS ENUM (
            'pending', 'in_progress', 'completed', 'reviewed', 'archived'
        );
    """)

    # -----------------------------------------------------------------------
    # 3. UTILITY FUNCTIONS  (used in RLS, triggers, before table creation)
    # -----------------------------------------------------------------------

    # Updated-at helper (general)
    _exec("""
          CREATE
          OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
          BEGIN
            NEW.updated_at
          = NOW();
          RETURN NEW;
          END;
        $$
          LANGUAGE plpgsql;
          """)

    # Alias used by later trigger definitions
    _exec("""
          CREATE
          OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
          BEGIN
            NEW.updated_at
          = NOW();
          RETURN NEW;
          END;
        $$
          LANGUAGE plpgsql;
          """)

    # RLS helper: returns true if auth.uid() is a member of the project
    # LANGUAGE plpgsql (not sql) to avoid creation-time validation of project_members
    # table reference — the table is created later in this same migration.
    _exec("""
          CREATE
          OR REPLACE FUNCTION is_project_member(p_project_id uuid, p_user_id uuid)
        RETURNS boolean
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        AS $$
          BEGIN
          RETURN EXISTS (SELECT 1
                         FROM project_members
                         WHERE project_id = p_project_id
                           AND user_id = p_user_id);
          END;
        $$;
          """)

    # RLS helper: returns true if auth.uid() is a manager of the project
    _exec("""
          CREATE
          OR REPLACE FUNCTION is_project_manager(p_project_id uuid, p_user_id uuid)
        RETURNS boolean
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        AS $$
          BEGIN
          RETURN EXISTS (SELECT 1
                         FROM project_members
                         WHERE project_id = p_project_id
                           AND user_id = p_user_id
                           AND role = 'manager');
          END;
        $$;
          """)

    # -----------------------------------------------------------------------
    # 4. TABLES  (ordered by dependency)
    # -----------------------------------------------------------------------

    # --- profiles -----------------------------------------------------------
    _exec("""
          CREATE TABLE profiles
          (
              id         uuid        NOT NULL PRIMARY KEY,
              email      text,
              full_name  text,
              avatar_url text,
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now(),
              CONSTRAINT profiles_id_fkey
                  FOREIGN KEY (id) REFERENCES auth.users (id) ON DELETE CASCADE
          );
          COMMENT
          ON TABLE profiles IS
            'Extended user profile data, keyed by auth.users.id.';
          """)

    # --- extraction_templates_global ----------------------------------------
    _exec("""
          CREATE TABLE extraction_templates_global
          (
              id          uuid                 NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              name        character varying    NOT NULL,
              description text,
              framework   extraction_framework NOT NULL,
              version     character varying    NOT NULL             DEFAULT '1.0.0',
              is_global   boolean              NOT NULL             DEFAULT true,
              schema      jsonb                NOT NULL             DEFAULT '{}',
              created_at  timestamptz          NOT NULL             DEFAULT now(),
              updated_at  timestamptz          NOT NULL             DEFAULT now()
          );
          """)

    # --- extraction_entity_types (depends on extraction_templates_global) ---
    _exec("""
          CREATE TABLE extraction_entity_types
          (
              id                    uuid                   NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              template_id           uuid,
              project_template_id   uuid,
              name                  character varying      NOT NULL,
              label                 character varying      NOT NULL,
              description           text,
              parent_entity_type_id uuid,
              cardinality           extraction_cardinality NOT NULL             DEFAULT 'one',
              sort_order            integer                NOT NULL             DEFAULT 0,
              is_required           boolean                NOT NULL             DEFAULT false,
              created_at            timestamptz            NOT NULL             DEFAULT now(),
              updated_at            timestamptz            NOT NULL             DEFAULT now(),
              CONSTRAINT extraction_entity_types_template_id_fkey
                  FOREIGN KEY (template_id) REFERENCES extraction_templates_global (id) ON DELETE CASCADE,
              CONSTRAINT extraction_entity_types_parent_entity_type_id_fkey
                  FOREIGN KEY (parent_entity_type_id) REFERENCES extraction_entity_types (id) ON DELETE CASCADE
          );
          """)

    # --- projects (depends on extraction_entity_types for assessment_entity_type_id) ---
    _exec("""
          CREATE TABLE projects
          (
              id                         uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              name                       character varying NOT NULL,
              description                text,
              created_by_id              uuid              NOT NULL,
              settings                   jsonb             NOT NULL             DEFAULT '{"blind_mode": false}',
              is_active                  boolean           NOT NULL             DEFAULT true,
              review_title               text,
              condition_studied          character varying,
              review_rationale           text,
              review_keywords            jsonb             NOT NULL             DEFAULT '[]',
              eligibility_criteria       jsonb             NOT NULL             DEFAULT '{}',
              study_design               jsonb             NOT NULL             DEFAULT '{}',
              review_context             text,
              search_strategy            text,
              risk_of_bias_instrument_id uuid,
              picots_config_ai_review    jsonb,
              review_type                review_type                            DEFAULT 'interventional',
              assessment_scope           character varying                      DEFAULT 'article',
              assessment_entity_type_id  uuid,
              created_at                 timestamptz       NOT NULL             DEFAULT now(),
              updated_at                 timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT projects_created_by_id_fkey
                  FOREIGN KEY (created_by_id) REFERENCES profiles (id) ON DELETE RESTRICT,
              CONSTRAINT projects_assessment_entity_type_id_fkey
                  FOREIGN KEY (assessment_entity_type_id) REFERENCES extraction_entity_types (id) ON DELETE SET NULL
          );
          COMMENT
          ON TABLE projects IS 'Systematic review projects.';
          """)

    # --- project_members ----------------------------------------------------
    _exec("""
          CREATE TABLE project_members
          (
              id                     uuid                NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id             uuid                NOT NULL,
              user_id                uuid                NOT NULL,
              role                   project_member_role NOT NULL             DEFAULT 'reviewer',
              permissions            jsonb               NOT NULL             DEFAULT '{"can_export": false}',
              invitation_email       text,
              invitation_token       text,
              invitation_sent_at     timestamptz,
              invitation_accepted_at timestamptz,
              created_by_id          uuid,
              created_at             timestamptz         NOT NULL             DEFAULT now(),
              updated_at             timestamptz         NOT NULL             DEFAULT now(),
              CONSTRAINT project_members_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT project_members_user_id_fkey
                  FOREIGN KEY (user_id) REFERENCES profiles (id) ON DELETE CASCADE,
              CONSTRAINT project_members_created_by_id_fkey
                  FOREIGN KEY (created_by_id) REFERENCES profiles (id) ON DELETE SET NULL,
              CONSTRAINT uq_project_user UNIQUE (project_id, user_id)
          );
          """)

    # --- articles -----------------------------------------------------------
    _exec("""
          CREATE TABLE articles
          (
              id                    uuid        NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id            uuid        NOT NULL,
              title                 text        NOT NULL,
              abstract              text,
              language              character varying,
              publication_year      integer,
              publication_month     integer,
              publication_day       integer,
              journal_title         text,
              journal_issn          character varying,
              journal_eissn         character varying,
              journal_publisher     text,
              volume                character varying,
              issue                 character varying,
              pages                 character varying,
              article_type          character varying,
              publication_status    character varying,
              open_access           boolean,
              license               character varying,
              doi                   text,
              pmid                  text,
              pmcid                 text,
              arxiv_id              text,
              pii                   text,
              keywords              text[],
              authors               text[],
              mesh_terms            text[],
              url_landing           text,
              url_pdf               text,
              study_design          character varying,
              registration          jsonb,
              funding               jsonb,
              conflicts_of_interest text,
              data_availability     text,
              hash_fingerprint      text,
              ingestion_source      character varying,
              source_payload        jsonb,
              row_version           bigint      NOT NULL             DEFAULT 1,
              zotero_item_key       text,
              zotero_collection_key text,
              zotero_version        integer,
              created_at            timestamptz NOT NULL             DEFAULT now(),
              updated_at            timestamptz NOT NULL             DEFAULT now(),
              CONSTRAINT articles_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
          );
          """)

    # --- project_extraction_templates ---------------------------------------
    _exec("""
          CREATE TABLE project_extraction_templates
          (
              id                 uuid                 NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id         uuid                 NOT NULL,
              global_template_id uuid,
              name               character varying    NOT NULL,
              description        text,
              framework          extraction_framework NOT NULL,
              version            character varying    NOT NULL             DEFAULT '1.0.0',
              schema             jsonb                NOT NULL             DEFAULT '{}',
              is_active          boolean              NOT NULL             DEFAULT true,
              created_by         uuid                 NOT NULL,
              created_at         timestamptz          NOT NULL             DEFAULT now(),
              updated_at         timestamptz          NOT NULL             DEFAULT now(),
              CONSTRAINT project_extraction_templates_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT project_extraction_templates_global_template_id_fkey
                  FOREIGN KEY (global_template_id) REFERENCES extraction_templates_global (id) ON DELETE SET NULL,
              CONSTRAINT project_extraction_templates_created_by_fkey
                  FOREIGN KEY (created_by) REFERENCES profiles (id) ON DELETE RESTRICT
          );
          """)

    # --- add FK from extraction_entity_types to project_extraction_templates ---
    # (project_extraction_templates is created after extraction_entity_types, so we add FK here)
    _exec("""
          ALTER TABLE extraction_entity_types
              ADD CONSTRAINT extraction_entity_types_project_template_id_fkey
                  FOREIGN KEY (project_template_id) REFERENCES project_extraction_templates (id) ON DELETE CASCADE;
          """)

    # --- assessment_instruments ---------------------------------------------
    _exec("""
          CREATE TABLE assessment_instruments
          (
              id                uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              tool_type         character varying NOT NULL,
              name              character varying NOT NULL,
              version           character varying NOT NULL             DEFAULT '1.0.0',
              mode              character varying NOT NULL             DEFAULT 'human',
              target_mode       character varying NOT NULL             DEFAULT 'per_article',
              is_active         boolean           NOT NULL             DEFAULT true,
              aggregation_rules jsonb,
              schema            jsonb,
              created_at        timestamptz       NOT NULL             DEFAULT now()
          );
          COMMENT
          ON TABLE assessment_instruments IS
            'Global (shared) assessment instruments (PROBAST, ROBIS, QUADAS-2, etc.).';
          """)

    # --- assessment_items ---------------------------------------------------
    _exec("""
          CREATE TABLE assessment_items
          (
              id                      uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              instrument_id           uuid              NOT NULL,
              domain                  character varying NOT NULL,
              item_code               character varying NOT NULL,
              question                text              NOT NULL,
              description             text,
              sort_order              integer           NOT NULL             DEFAULT 0,
              required                boolean           NOT NULL             DEFAULT true,
              allowed_levels          jsonb             NOT NULL,
              allowed_levels_override jsonb,
              llm_prompt              text,
              created_at              timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT assessment_items_instrument_id_fkey
                  FOREIGN KEY (instrument_id) REFERENCES assessment_instruments (id) ON DELETE CASCADE,
              CONSTRAINT uq_assessment_items_code UNIQUE (instrument_id, item_code)
          );
          """)

    # --- article_files (current schema: storage_key, project_id, file_role, extraction fields) --
    _exec("""
          CREATE TABLE article_files
          (
              id                uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id        uuid              NOT NULL,
              article_id        uuid              NOT NULL,
              file_type         character varying NOT NULL,
              storage_key       text              NOT NULL,
              original_filename text,
              bytes             bigint,
              md5               text,
              file_role         file_role                              DEFAULT 'MAIN',
              text_raw          text,
              text_html         text,
              extraction_status character varying                      DEFAULT 'pending',
              extraction_error  text,
              extracted_at      timestamptz,
              created_at        timestamptz       NOT NULL             DEFAULT now(),
              updated_at        timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT article_files_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT article_files_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE
          );
          """)

    # --- article_highlights, article_boxes, article_annotations (from 0004) --
    _exec("""
          CREATE TABLE article_highlights
          (
              id               uuid        NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              article_id       uuid        NOT NULL,
              article_file_id  uuid,
              user_id          uuid,
              page_number      integer,
              position         jsonb,
              highlighted_text text,
              color            character varying                DEFAULT 'yellow',
              created_at       timestamptz NOT NULL             DEFAULT now(),
              CONSTRAINT article_highlights_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
              CONSTRAINT article_highlights_article_file_id_fkey
                  FOREIGN KEY (article_file_id) REFERENCES article_files (id) ON DELETE SET NULL,
              CONSTRAINT article_highlights_user_id_fkey
                  FOREIGN KEY (user_id) REFERENCES auth.users (id) ON DELETE SET NULL
          );
          """)
    _exec("""
          CREATE TABLE article_boxes
          (
              id              uuid        NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              article_id      uuid        NOT NULL,
              article_file_id uuid,
              user_id         uuid,
              page_number     integer,
              position        jsonb,
              label           character varying,
              color           character varying                DEFAULT 'blue',
              created_at      timestamptz NOT NULL             DEFAULT now(),
              CONSTRAINT article_boxes_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
              CONSTRAINT article_boxes_article_file_id_fkey
                  FOREIGN KEY (article_file_id) REFERENCES article_files (id) ON DELETE SET NULL,
              CONSTRAINT article_boxes_user_id_fkey
                  FOREIGN KEY (user_id) REFERENCES auth.users (id) ON DELETE SET NULL
          );
          """)
    _exec("""
          CREATE TABLE article_annotations
          (
              id              uuid        NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              article_id      uuid        NOT NULL,
              article_file_id uuid,
              user_id         uuid,
              page_number     integer,
              position        jsonb,
              content         text,
              created_at      timestamptz NOT NULL             DEFAULT now(),
              updated_at      timestamptz NOT NULL             DEFAULT now(),
              CONSTRAINT article_annotations_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
              CONSTRAINT article_annotations_article_file_id_fkey
                  FOREIGN KEY (article_file_id) REFERENCES article_files (id) ON DELETE SET NULL,
              CONSTRAINT article_annotations_user_id_fkey
                  FOREIGN KEY (user_id) REFERENCES auth.users (id) ON DELETE SET NULL
          );
          """)

    # --- extraction_fields --------------------------------------------------
    _exec("""
          CREATE TABLE extraction_fields
          (
              id                uuid                  NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              entity_type_id    uuid                  NOT NULL,
              name              character varying     NOT NULL,
              label             character varying     NOT NULL,
              description       text,
              field_type        extraction_field_type NOT NULL,
              is_required       boolean               NOT NULL             DEFAULT false,
              validation_schema jsonb,
              allowed_values    jsonb,
              unit              character varying,
              allowed_units     jsonb,
              sort_order        integer               NOT NULL             DEFAULT 0,
              llm_description   text,
              allow_other       boolean NOT NULL DEFAULT false,
              other_label       character varying,
              other_placeholder character varying,
              created_at        timestamptz           NOT NULL             DEFAULT now(),
              updated_at        timestamptz           NOT NULL             DEFAULT now(),
              CONSTRAINT extraction_fields_entity_type_id_fkey
                  FOREIGN KEY (entity_type_id) REFERENCES extraction_entity_types (id) ON DELETE CASCADE
          );
          """)

    # --- extraction_instances -----------------------------------------------
    _exec("""
          CREATE TABLE extraction_instances
          (
              id                 uuid                       NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id         uuid                       NOT NULL,
              article_id         uuid,
              template_id        uuid                       NOT NULL,
              entity_type_id     uuid                       NOT NULL,
              parent_instance_id uuid,
              label              character varying          NOT NULL,
              sort_order         integer                    NOT NULL             DEFAULT 0,
              metadata           jsonb                      NOT NULL             DEFAULT '{}',
              created_by         uuid                       NOT NULL,
              status             extraction_instance_status NOT NULL             DEFAULT 'pending',
              is_template        boolean,
              created_at         timestamptz                NOT NULL             DEFAULT now(),
              updated_at         timestamptz                NOT NULL             DEFAULT now(),
              CONSTRAINT extraction_instances_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT extraction_instances_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
              CONSTRAINT extraction_instances_template_id_fkey
                  FOREIGN KEY (template_id) REFERENCES project_extraction_templates (id) ON DELETE RESTRICT,
              CONSTRAINT extraction_instances_entity_type_id_fkey
                  FOREIGN KEY (entity_type_id) REFERENCES extraction_entity_types (id) ON DELETE RESTRICT,
              CONSTRAINT extraction_instances_parent_instance_id_fkey
                  FOREIGN KEY (parent_instance_id) REFERENCES extraction_instances (id) ON DELETE CASCADE,
              CONSTRAINT extraction_instances_created_by_fkey
                  FOREIGN KEY (created_by) REFERENCES profiles (id) ON DELETE RESTRICT
          );
          """)

    # --- extraction_runs ----------------------------------------------------
    _exec("""
          CREATE TABLE extraction_runs
          (
              id            uuid                  NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id    uuid                  NOT NULL,
              article_id    uuid                  NOT NULL,
              template_id   uuid                  NOT NULL,
              stage         extraction_run_stage  NOT NULL,
              status        extraction_run_status NOT NULL             DEFAULT 'pending',
              parameters    jsonb                 NOT NULL             DEFAULT '{}',
              results       jsonb                 NOT NULL             DEFAULT '{}',
              error_message text,
              started_at    timestamptz,
              completed_at  timestamptz,
              created_by    uuid                  NOT NULL,
              created_at    timestamptz           NOT NULL             DEFAULT now(),
              CONSTRAINT extraction_runs_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT extraction_runs_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
              CONSTRAINT extraction_runs_template_id_fkey
                  FOREIGN KEY (template_id) REFERENCES project_extraction_templates (id) ON DELETE RESTRICT,
              CONSTRAINT extraction_runs_created_by_fkey
                  FOREIGN KEY (created_by) REFERENCES profiles (id) ON DELETE RESTRICT
          );
          COMMENT
          ON TABLE extraction_runs IS 'Tracks AI extraction execution lifecycle.';
          """)

    # --- ai_assessment_configs (from 0008) ----------------------------------
    _exec("""
          CREATE TABLE ai_assessment_configs
          (
              id                 uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id         uuid              NOT NULL,
              instrument_id      uuid,
              model_name         character varying NOT NULL             DEFAULT 'google/gemini-2.5-flash',
              temperature        numeric           NOT NULL             DEFAULT 0.3,
              max_tokens         integer           NOT NULL             DEFAULT 2000,
              system_instruction text,
              is_active          boolean           NOT NULL             DEFAULT true,
              created_at         timestamptz       NOT NULL             DEFAULT now(),
              updated_at         timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT ai_assessment_configs_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT ai_assessment_configs_instrument_id_fkey
                  FOREIGN KEY (instrument_id) REFERENCES assessment_instruments (id) ON DELETE SET NULL
          );
          """)

    # --- ai_assessment_prompts ----------------------------------------------
    _exec("""
          CREATE TABLE ai_assessment_prompts
          (
              id                   uuid        NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              assessment_item_id   uuid        NOT NULL UNIQUE,
              system_prompt        text        NOT NULL             DEFAULT 'You are an expert research quality assessor. Analyze the provided research article and answer the specific question based on the evidence found in the text.',
              user_prompt_template text        NOT NULL             DEFAULT 'Based on the article content, assess: {{question}}

Available response levels: {{levels}}

Provide your assessment with clear justification and cite specific passages from the text that support your conclusion.',
              created_at           timestamptz NOT NULL             DEFAULT now(),
              updated_at           timestamptz NOT NULL             DEFAULT now(),
              CONSTRAINT ai_assessment_prompts_assessment_item_id_fkey
                  FOREIGN KEY (assessment_item_id) REFERENCES assessment_items (id) ON DELETE CASCADE
          );
          """)

    # --- ai_assessments (final state: per-item AI assessment results) -------
    _exec("""
          CREATE TABLE ai_assessments
          (
              id                 uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id         uuid              NOT NULL,
              article_id         uuid              NOT NULL,
              assessment_item_id uuid              NOT NULL,
              instrument_id      uuid              NOT NULL,
              user_id            uuid              NOT NULL,
              selected_level     character varying NOT NULL,
              confidence_score   numeric,
              justification      text              NOT NULL,
              evidence_passages  jsonb             NOT NULL             DEFAULT '[]',
              ai_model_used      character varying NOT NULL,
              processing_time_ms integer,
              prompt_tokens      integer,
              completion_tokens  integer,
              status             character varying NOT NULL             DEFAULT 'pending_review',
              reviewed_at        timestamptz,
              human_response     character varying,
              article_file_id    uuid,
              created_at         timestamptz       NOT NULL             DEFAULT now(),
              updated_at         timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT ai_assessments_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT ai_assessments_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
              CONSTRAINT ai_assessments_assessment_item_id_fkey
                  FOREIGN KEY (assessment_item_id) REFERENCES assessment_items (id) ON DELETE RESTRICT,
              CONSTRAINT ai_assessments_instrument_id_fkey
                  FOREIGN KEY (instrument_id) REFERENCES assessment_instruments (id) ON DELETE RESTRICT,
              CONSTRAINT ai_assessments_user_id_fkey
                  FOREIGN KEY (user_id) REFERENCES profiles (id) ON DELETE RESTRICT,
              CONSTRAINT ai_assessments_article_file_id_fkey
                  FOREIGN KEY (article_file_id) REFERENCES article_files (id) ON DELETE SET NULL
          );
          COMMENT
          ON TABLE ai_assessments IS
            'Per-item AI assessment results (post-0030 restructure).';
          """)

    # --- project_assessment_instruments (from 0034) -------------------------
    _exec("""
          CREATE TABLE project_assessment_instruments
          (
              id                   uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id           uuid              NOT NULL,
              global_instrument_id uuid,
              name                 character varying NOT NULL,
              description          text,
              tool_type            character varying NOT NULL,
              version              character varying NOT NULL             DEFAULT '1.0.0',
              mode                 character varying NOT NULL             DEFAULT 'human',
              target_mode          character varying NOT NULL             DEFAULT 'per_article',
              is_active            boolean           NOT NULL             DEFAULT true,
              aggregation_rules    jsonb,
              schema               jsonb,
              created_by           uuid              NOT NULL,
              created_at           timestamptz       NOT NULL             DEFAULT now(),
              updated_at           timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT project_assessment_instruments_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT project_assessment_instruments_global_instrument_id_fkey
                  FOREIGN KEY (global_instrument_id) REFERENCES assessment_instruments (id) ON DELETE SET NULL,
              CONSTRAINT project_assessment_instruments_created_by_fkey
                  FOREIGN KEY (created_by) REFERENCES profiles (id) ON DELETE RESTRICT
          );
          """)

    # --- project_assessment_items (from 0034) -------------------------------
    _exec("""
          CREATE TABLE project_assessment_items
          (
              id                      uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_instrument_id   uuid              NOT NULL,
              global_item_id          uuid,
              domain                  character varying NOT NULL,
              item_code               character varying NOT NULL,
              question                text              NOT NULL,
              description             text,
              sort_order              integer           NOT NULL             DEFAULT 0,
              required                boolean           NOT NULL             DEFAULT true,
              allowed_levels          jsonb             NOT NULL,
              allowed_levels_override jsonb,
              llm_prompt              text,
              created_at              timestamptz       NOT NULL             DEFAULT now(),
              updated_at              timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT project_assessment_items_project_instrument_id_fkey
                  FOREIGN KEY (project_instrument_id) REFERENCES project_assessment_instruments (id) ON DELETE CASCADE,
              CONSTRAINT project_assessment_items_global_item_id_fkey
                  FOREIGN KEY (global_item_id) REFERENCES assessment_items (id) ON DELETE SET NULL,
              CONSTRAINT uq_project_assessment_item_code UNIQUE (project_instrument_id, item_code)
          );
          """)

    # --- ai_assessment_runs (from 0027, final state includes 20260218 changes) --
    _exec("""
          CREATE TABLE ai_assessment_runs
          (
              id                     uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id             uuid              NOT NULL,
              article_id             uuid              NOT NULL,
              instrument_id          uuid,
              project_instrument_id  uuid,
              extraction_instance_id uuid,
              stage                  character varying NOT NULL,
              status                 character varying NOT NULL             DEFAULT 'pending',
              parameters             jsonb             NOT NULL             DEFAULT '{}',
              results                jsonb             NOT NULL             DEFAULT '{}',
              error_message          text,
              started_at             timestamptz,
              completed_at           timestamptz,
              created_by             uuid              NOT NULL,
              created_at             timestamptz       NOT NULL             DEFAULT now(),
              updated_at             timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT ai_assessment_runs_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT ai_assessment_runs_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
              CONSTRAINT ai_assessment_runs_instrument_id_fkey
                  FOREIGN KEY (instrument_id) REFERENCES assessment_instruments (id) ON DELETE RESTRICT,
              CONSTRAINT ai_assessment_runs_project_instrument_id_fkey
                  FOREIGN KEY (project_instrument_id) REFERENCES project_assessment_instruments (id) ON DELETE RESTRICT,
              CONSTRAINT ai_assessment_runs_extraction_instance_id_fkey
                  FOREIGN KEY (extraction_instance_id) REFERENCES extraction_instances (id) ON DELETE CASCADE,
              CONSTRAINT ai_assessment_runs_created_by_fkey
                  FOREIGN KEY (created_by) REFERENCES profiles (id) ON DELETE RESTRICT
          );
          COMMENT
          ON TABLE ai_assessment_runs IS
            'Tracks AI assessment execution lifecycle (similar to extraction_runs).';
          """)

    # --- ai_suggestions (final state: run_id→extraction_run_id nullable, +assessment_run_id, +project_assessment_item_id) --
    _exec("""
          CREATE TABLE ai_suggestions
          (
              id                         uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              extraction_run_id          uuid,
              instance_id                uuid,
              field_id                   uuid,
              assessment_item_id         uuid,
              assessment_run_id          uuid,
              project_assessment_item_id uuid,
              suggested_value            jsonb             NOT NULL,
              confidence_score           numeric
                  CHECK (confidence_score IS NULL OR (confidence_score >= 0.0 AND confidence_score <= 1.0)),
              reasoning                  text,
              status                     suggestion_status NOT NULL             DEFAULT 'pending',
              reviewed_by                uuid,
              reviewed_at                timestamptz,
              created_at                 timestamptz       NOT NULL             DEFAULT now(),
              metadata                   jsonb             NOT NULL             DEFAULT '{}',
              CONSTRAINT ai_suggestions_extraction_run_id_fkey
                  FOREIGN KEY (extraction_run_id) REFERENCES extraction_runs (id) ON DELETE CASCADE,
              CONSTRAINT ai_suggestions_instance_id_fkey
                  FOREIGN KEY (instance_id) REFERENCES extraction_instances (id) ON DELETE CASCADE,
              CONSTRAINT ai_suggestions_field_id_fkey
                  FOREIGN KEY (field_id) REFERENCES extraction_fields (id) ON DELETE RESTRICT,
              CONSTRAINT ai_suggestions_assessment_item_id_fkey
                  FOREIGN KEY (assessment_item_id) REFERENCES assessment_items (id) ON DELETE CASCADE,
              CONSTRAINT ai_suggestions_assessment_run_id_fkey
                  FOREIGN KEY (assessment_run_id) REFERENCES ai_assessment_runs (id) ON DELETE CASCADE,
              CONSTRAINT ai_suggestions_project_assessment_item_id_fkey
                  FOREIGN KEY (project_assessment_item_id) REFERENCES project_assessment_items (id) ON DELETE SET NULL,
              CONSTRAINT ai_suggestions_reviewed_by_fkey
                  FOREIGN KEY (reviewed_by) REFERENCES profiles (id) ON DELETE SET NULL
          );
          COMMENT
          ON TABLE ai_suggestions IS
            'AI suggestions for extraction (extraction_run_id set) or assessment (assessment_run_id set).';
          """)

    # --- extracted_values (depends on ai_suggestions) -----------------------
    _exec("""
          CREATE TABLE extracted_values
          (
              id               uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id       uuid              NOT NULL,
              article_id       uuid              NOT NULL,
              instance_id      uuid              NOT NULL,
              field_id         uuid              NOT NULL,
              value            jsonb             NOT NULL             DEFAULT '{}',
              source           extraction_source NOT NULL,
              confidence_score numeric,
              evidence         jsonb             NOT NULL             DEFAULT '[]',
              reviewer_id      uuid,
              is_consensus     boolean           NOT NULL             DEFAULT false,
              ai_suggestion_id uuid,
              unit             character varying,
              created_at       timestamptz       NOT NULL             DEFAULT now(),
              updated_at       timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT extracted_values_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT extracted_values_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
              CONSTRAINT extracted_values_instance_id_fkey
                  FOREIGN KEY (instance_id) REFERENCES extraction_instances (id) ON DELETE CASCADE,
              CONSTRAINT extracted_values_field_id_fkey
                  FOREIGN KEY (field_id) REFERENCES extraction_fields (id) ON DELETE RESTRICT,
              CONSTRAINT extracted_values_reviewer_id_fkey
                  FOREIGN KEY (reviewer_id) REFERENCES profiles (id) ON DELETE SET NULL,
              CONSTRAINT extracted_values_ai_suggestion_id_fkey
                  FOREIGN KEY (ai_suggestion_id) REFERENCES ai_suggestions (id) ON DELETE SET NULL
          );
          """)

    # --- extraction_evidence ------------------------------------------------
    _exec("""
          CREATE TABLE extraction_evidence
          (
              id              uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id      uuid              NOT NULL,
              article_id      uuid              NOT NULL,
              target_type     character varying NOT NULL,
              target_id       uuid              NOT NULL,
              article_file_id uuid,
              page_number     integer,
              position        jsonb,
              text_content    text,
              created_by      uuid              NOT NULL,
              created_at      timestamptz       NOT NULL             DEFAULT now(),
              updated_at      timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT extraction_evidence_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT extraction_evidence_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
              CONSTRAINT extraction_evidence_article_file_id_fkey
                  FOREIGN KEY (article_file_id) REFERENCES article_files (id) ON DELETE SET NULL,
              CONSTRAINT extraction_evidence_created_by_fkey
                  FOREIGN KEY (created_by) REFERENCES profiles (id) ON DELETE RESTRICT
          );
          """)

    # --- assessment_instances (final state: instrument_id nullable, +project_instrument_id) --
    _exec("""
          CREATE TABLE assessment_instances
          (
              id                     uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id             uuid              NOT NULL,
              article_id             uuid              NOT NULL,
              instrument_id          uuid,
              project_instrument_id  uuid,
              extraction_instance_id uuid,
              parent_instance_id     uuid,
              label                  character varying NOT NULL,
              status                 assessment_status NOT NULL             DEFAULT 'in_progress',
              reviewer_id            uuid              NOT NULL,
              is_blind               boolean           NOT NULL             DEFAULT false,
              can_see_others         boolean           NOT NULL             DEFAULT true,
              metadata               jsonb             NOT NULL             DEFAULT '{}',
              created_at             timestamptz       NOT NULL             DEFAULT now(),
              updated_at             timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT assessment_instances_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT assessment_instances_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
              CONSTRAINT assessment_instances_instrument_id_fkey
                  FOREIGN KEY (instrument_id) REFERENCES assessment_instruments (id) ON DELETE RESTRICT,
              CONSTRAINT assessment_instances_project_instrument_id_fkey
                  FOREIGN KEY (project_instrument_id) REFERENCES project_assessment_instruments (id) ON DELETE RESTRICT,
              CONSTRAINT assessment_instances_extraction_instance_id_fkey
                  FOREIGN KEY (extraction_instance_id) REFERENCES extraction_instances (id) ON DELETE SET NULL,
              CONSTRAINT assessment_instances_parent_instance_id_fkey
                  FOREIGN KEY (parent_instance_id) REFERENCES assessment_instances (id) ON DELETE CASCADE,
              CONSTRAINT assessment_instances_reviewer_id_fkey
                  FOREIGN KEY (reviewer_id) REFERENCES profiles (id) ON DELETE RESTRICT
          );
          COMMENT
          ON TABLE assessment_instances IS
            'Assessment instances. Analogue of extraction_instances.';
          """)

    # --- assessment_responses (assessment_item_id NOT NULL, references assessment_items) --
    _exec("""
          CREATE TABLE assessment_responses
          (
              id                     uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id             uuid              NOT NULL,
              article_id             uuid              NOT NULL,
              assessment_instance_id uuid              NOT NULL,
              assessment_item_id     uuid              NOT NULL,
              selected_level         character varying NOT NULL,
              notes                  text,
              confidence             numeric(3, 2)
                  CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
              source                 assessment_source NOT NULL             DEFAULT 'human',
              confidence_score       numeric(3, 2)
                  CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)),
              ai_suggestion_id       uuid,
              reviewer_id            uuid              NOT NULL,
              is_consensus           boolean           NOT NULL             DEFAULT false,
              created_at             timestamptz       NOT NULL             DEFAULT now(),
              updated_at             timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT assessment_responses_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT assessment_responses_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
              CONSTRAINT assessment_responses_assessment_instance_id_fkey
                  FOREIGN KEY (assessment_instance_id) REFERENCES assessment_instances (id) ON DELETE CASCADE,
              CONSTRAINT assessment_responses_assessment_item_id_fkey
                  FOREIGN KEY (assessment_item_id) REFERENCES assessment_items (id) ON DELETE RESTRICT,
              CONSTRAINT assessment_responses_reviewer_id_fkey
                  FOREIGN KEY (reviewer_id) REFERENCES profiles (id) ON DELETE RESTRICT,
              CONSTRAINT assessment_responses_ai_suggestion_id_fkey
                  FOREIGN KEY (ai_suggestion_id) REFERENCES ai_assessments (id) ON DELETE SET NULL
          );
          COMMENT
          ON TABLE assessment_responses IS
            'Individual item responses. Analogue of extracted_values.';
          """)

    # --- assessment_evidence ------------------------------------------------
    _exec("""
          CREATE TABLE assessment_evidence
          (
              id              uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              project_id      uuid              NOT NULL,
              article_id      uuid              NOT NULL,
              target_type     character varying NOT NULL
                  CHECK (target_type IN ('response', 'instance')),
              target_id       uuid              NOT NULL,
              article_file_id uuid,
              page_number     integer CHECK (page_number IS NULL OR page_number > 0),
              position        jsonb                                  DEFAULT '{}' CHECK (jsonb_typeof(position) = 'object'),
              text_content    text,
              created_by      uuid              NOT NULL,
              created_at      timestamptz       NOT NULL             DEFAULT now(),
              updated_at      timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT assessment_evidence_project_id_fkey
                  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
              CONSTRAINT assessment_evidence_article_id_fkey
                  FOREIGN KEY (article_id) REFERENCES articles (id) ON DELETE CASCADE,
              CONSTRAINT assessment_evidence_article_file_id_fkey
                  FOREIGN KEY (article_file_id) REFERENCES article_files (id) ON DELETE SET NULL,
              CONSTRAINT assessment_evidence_created_by_fkey
                  FOREIGN KEY (created_by) REFERENCES profiles (id) ON DELETE RESTRICT
          );
          """)

    # --- zotero_integrations ------------------------------------------------
    _exec("""
          CREATE TABLE zotero_integrations
          (
              id                uuid        NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              user_id           uuid        NOT NULL UNIQUE,
              zotero_user_id    text        NOT NULL,
              library_type      text        NOT NULL,
              is_active         boolean     NOT NULL             DEFAULT true,
              last_sync_at      timestamptz,
              encrypted_api_key text,
              created_at        timestamptz NOT NULL             DEFAULT now(),
              updated_at        timestamptz NOT NULL             DEFAULT now(),
              CONSTRAINT zotero_integrations_user_id_fkey
                  FOREIGN KEY (user_id) REFERENCES profiles (id) ON DELETE CASCADE
          );
          """)

    # --- feedback_reports ---------------------------------------------------
    _exec("""
          CREATE TABLE feedback_reports
          (
              id         uuid              NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              user_id    uuid,
              category   character varying NOT NULL,
              message    text              NOT NULL,
              metadata   jsonb             NOT NULL             DEFAULT '{}',
              status     character varying NOT NULL             DEFAULT 'open',
              created_at timestamptz       NOT NULL             DEFAULT now(),
              updated_at timestamptz       NOT NULL             DEFAULT now(),
              CONSTRAINT feedback_reports_user_id_fkey
                  FOREIGN KEY (user_id) REFERENCES auth.users (id) ON DELETE SET NULL
          );
          """)

    # --- user_api_keys (from 0022) ------------------------------------------
    _exec("""
          CREATE TABLE user_api_keys
          (
              id                uuid        NOT NULL PRIMARY KEY DEFAULT gen_random_uuid(),
              user_id           uuid        NOT NULL,
              provider          text        NOT NULL,
              encrypted_api_key text        NOT NULL,
              key_name          text,
              is_active         boolean     NOT NULL             DEFAULT true,
              is_default        boolean     NOT NULL             DEFAULT false,
              last_used_at      timestamptz,
              last_validated_at timestamptz,
              validation_status text,
              metadata          jsonb,
              created_at        timestamptz NOT NULL             DEFAULT now(),
              updated_at        timestamptz NOT NULL             DEFAULT now(),
              CONSTRAINT user_api_keys_user_id_fkey
                  FOREIGN KEY (user_id) REFERENCES profiles (id) ON DELETE CASCADE,
              CONSTRAINT user_api_keys_provider_check
                  CHECK (provider IN ('openai', 'anthropic', 'gemini', 'grok')),
              CONSTRAINT user_api_keys_validation_status_check
                  CHECK (validation_status IS NULL OR validation_status IN ('valid', 'invalid', 'pending'))
          );
          """)

    # --- migration_status (from 0032; managed externally, excluded from drift) --
    _exec("""
          CREATE TABLE migration_status
          (
              id             serial PRIMARY KEY,
              migration_name character varying NOT NULL UNIQUE,
              executed_at    timestamptz       NOT NULL DEFAULT now(),
              notes          text
          );
          INSERT INTO migration_status (migration_name, notes)
          VALUES ('0032_cleanup_legacy_assessment',
                  'Removed legacy assessments table, created assessment_instances/responses/evidence');
          """)

    # -----------------------------------------------------------------------
    # 5. INDEXES
    # -----------------------------------------------------------------------

    # --- projects ---
    _exec("CREATE INDEX idx_projects_created_by_id ON projects(created_by_id);")
    _exec("CREATE INDEX idx_projects_settings_gin ON projects USING gin(settings);")
    _exec("CREATE INDEX idx_projects_review_keywords_gin ON projects USING gin(review_keywords);")
    _exec(
        "CREATE INDEX idx_projects_eligibility_criteria_gin ON projects USING gin(eligibility_criteria);"
    )
    _exec("CREATE INDEX idx_projects_study_design_gin ON projects USING gin(study_design);")

    # --- project_members ---
    _exec("CREATE INDEX idx_project_members_project_id ON project_members(project_id);")
    _exec("CREATE INDEX idx_project_members_user_id ON project_members(user_id);")

    # --- articles ---
    _exec("CREATE INDEX idx_articles_project_id ON articles(project_id);")
    _exec("CREATE INDEX idx_articles_doi ON articles(doi) WHERE doi IS NOT NULL;")
    _exec("CREATE INDEX idx_articles_pmid ON articles(pmid) WHERE pmid IS NOT NULL;")
    _exec("CREATE INDEX idx_articles_biblio ON articles(publication_year, journal_title);")
    _exec("CREATE INDEX idx_articles_trgm_title ON articles USING gin(title gin_trgm_ops);")
    _exec("CREATE INDEX idx_articles_keywords ON articles USING gin(keywords);")
    _exec("CREATE INDEX idx_articles_mesh ON articles USING gin(mesh_terms);")
    _exec("CREATE INDEX idx_articles_source_payload_gin ON articles USING gin(source_payload);")
    _exec("""
          CREATE UNIQUE INDEX uq_articles_project_zotero_item
              ON articles (project_id, zotero_item_key) WHERE zotero_item_key IS NOT NULL;
          """)

    # --- article_files ---
    _exec("CREATE INDEX idx_article_files_project_id ON article_files(project_id);")
    _exec("CREATE INDEX idx_article_files_article_id ON article_files(article_id);")
    _exec("CREATE INDEX idx_article_files_article_role ON article_files(article_id, file_role);")

    # --- extraction_templates_global ---
    _exec(
        "CREATE INDEX idx_extraction_templates_global_schema_gin ON extraction_templates_global USING gin(schema);"
    )

    # --- project_extraction_templates ---
    _exec(
        "CREATE INDEX idx_project_extraction_templates_project_id ON project_extraction_templates(project_id);"
    )
    _exec(
        "CREATE INDEX idx_project_extraction_templates_schema_gin ON project_extraction_templates USING gin(schema);"
    )

    # --- extraction_entity_types ---
    _exec(
        "CREATE INDEX idx_extraction_entity_types_template ON extraction_entity_types(template_id);"
    )
    _exec(
        "CREATE INDEX idx_extraction_entity_types_parent ON extraction_entity_types(parent_entity_type_id) WHERE parent_entity_type_id IS NOT NULL;"
    )

    # --- extraction_fields ---
    _exec("CREATE INDEX idx_extraction_fields_entity_type ON extraction_fields(entity_type_id);")

    # --- extraction_instances ---
    _exec("CREATE INDEX idx_extraction_instances_project ON extraction_instances(project_id);")
    _exec("CREATE INDEX idx_extraction_instances_article ON extraction_instances(article_id);")
    _exec("CREATE INDEX idx_extraction_instances_template ON extraction_instances(template_id);")
    _exec(
        "CREATE INDEX idx_extraction_instances_entity_type ON extraction_instances(entity_type_id);"
    )
    _exec(
        "CREATE INDEX idx_extraction_instances_parent ON extraction_instances(parent_instance_id) WHERE parent_instance_id IS NOT NULL;"
    )
    _exec("CREATE INDEX idx_extraction_instances_status ON extraction_instances(status);")
    _exec(
        "CREATE INDEX idx_extraction_instances_article_entity_sort ON extraction_instances(article_id, entity_type_id, sort_order);"
    )
    _exec(
        "CREATE INDEX idx_extraction_instances_metadata_gin ON extraction_instances USING gin(metadata);"
    )

    # --- extracted_values ---
    _exec("CREATE INDEX idx_extracted_values_project_id ON extracted_values(project_id);")
    _exec("CREATE INDEX idx_extracted_values_article_id ON extracted_values(article_id);")
    _exec("CREATE INDEX idx_extracted_values_instance_id ON extracted_values(instance_id);")
    _exec("CREATE INDEX idx_extracted_values_field_id ON extracted_values(field_id);")
    _exec(
        "CREATE INDEX idx_extracted_values_instance_field ON extracted_values(instance_id, field_id);"
    )
    _exec("CREATE INDEX idx_extracted_values_value_gin ON extracted_values USING gin(value);")
    _exec("CREATE INDEX idx_extracted_values_evidence_gin ON extracted_values USING gin(evidence);")

    # --- extraction_evidence ---
    _exec("CREATE INDEX idx_extraction_evidence_project_id ON extraction_evidence(project_id);")
    _exec("CREATE INDEX idx_extraction_evidence_article_id ON extraction_evidence(article_id);")
    _exec(
        "CREATE INDEX idx_extraction_evidence_position_gin ON extraction_evidence USING gin(position);"
    )

    # --- extraction_runs ---
    _exec("CREATE INDEX idx_extraction_runs_project ON extraction_runs(project_id);")
    _exec("CREATE INDEX idx_extraction_runs_article ON extraction_runs(article_id);")
    _exec("CREATE INDEX idx_extraction_runs_template ON extraction_runs(template_id);")
    _exec("CREATE INDEX idx_extraction_runs_status_stage ON extraction_runs(status, stage);")
    _exec(
        "CREATE INDEX idx_extraction_runs_parameters_gin ON extraction_runs USING gin(parameters);"
    )
    _exec("CREATE INDEX idx_extraction_runs_results_gin ON extraction_runs USING gin(results);")

    # --- assessment_instruments ---
    _exec("CREATE INDEX idx_assessment_instruments_tool_type ON assessment_instruments(tool_type);")

    # --- assessment_items ---
    _exec("CREATE INDEX idx_assessment_items_instrument ON assessment_items(instrument_id);")

    # --- ai_assessment_configs ---
    _exec("CREATE INDEX idx_ai_assessment_configs_project ON ai_assessment_configs(project_id);")

    # --- ai_assessments ---
    _exec("CREATE INDEX idx_ai_assessments_project ON ai_assessments(project_id);")
    _exec("CREATE INDEX idx_ai_assessments_article ON ai_assessments(article_id);")
    _exec(
        "CREATE INDEX idx_ai_assessments_evidence_gin ON ai_assessments USING gin(evidence_passages);"
    )

    # --- project_assessment_instruments ---
    _exec(
        "CREATE INDEX idx_project_assessment_instruments_project_id ON project_assessment_instruments(project_id);"
    )
    _exec(
        "CREATE INDEX idx_project_assessment_instruments_active ON project_assessment_instruments(project_id, is_active) WHERE is_active = true;"
    )

    # --- project_assessment_items ---
    _exec(
        "CREATE INDEX idx_project_assessment_items_instrument_id ON project_assessment_items(project_instrument_id);"
    )
    _exec(
        "CREATE INDEX idx_project_assessment_items_domain ON project_assessment_items(project_instrument_id, domain);"
    )

    # --- ai_assessment_runs ---
    _exec("CREATE INDEX idx_ai_assessment_runs_status ON ai_assessment_runs(status, stage);")
    _exec("CREATE INDEX idx_ai_assessment_runs_project ON ai_assessment_runs(project_id);")
    _exec("CREATE INDEX idx_ai_assessment_runs_article ON ai_assessment_runs(article_id);")
    _exec(
        "CREATE INDEX idx_ai_assessment_runs_instrument ON ai_assessment_runs(instrument_id) WHERE instrument_id IS NOT NULL;"
    )
    _exec(
        "CREATE INDEX idx_ai_assessment_runs_project_instrument ON ai_assessment_runs(project_instrument_id) WHERE project_instrument_id IS NOT NULL;"
    )
    _exec(
        "CREATE INDEX idx_ai_assessment_runs_instance ON ai_assessment_runs(extraction_instance_id) WHERE extraction_instance_id IS NOT NULL;"
    )
    _exec("CREATE INDEX idx_ai_assessment_runs_created_by ON ai_assessment_runs(created_by);")
    _exec(
        "CREATE INDEX idx_ai_assessment_runs_parameters_gin ON ai_assessment_runs USING gin(parameters);"
    )
    _exec(
        "CREATE INDEX idx_ai_assessment_runs_results_gin ON ai_assessment_runs USING gin(results);"
    )

    # --- ai_suggestions ---
    _exec(
        "CREATE INDEX idx_ai_suggestions_extraction_run_id ON ai_suggestions(extraction_run_id) WHERE extraction_run_id IS NOT NULL;"
    )
    _exec(
        "CREATE INDEX idx_ai_suggestions_assessment_run_id ON ai_suggestions(assessment_run_id) WHERE assessment_run_id IS NOT NULL;"
    )
    _exec(
        "CREATE INDEX idx_ai_suggestions_instance_id ON ai_suggestions(instance_id) WHERE instance_id IS NOT NULL;"
    )
    _exec(
        "CREATE INDEX idx_ai_suggestions_field_id ON ai_suggestions(field_id) WHERE field_id IS NOT NULL;"
    )
    _exec(
        "CREATE INDEX idx_ai_suggestions_assessment_item_id ON ai_suggestions(assessment_item_id) WHERE assessment_item_id IS NOT NULL;"
    )
    _exec(
        "CREATE INDEX idx_ai_suggestions_project_assessment_item_id ON ai_suggestions(project_assessment_item_id) WHERE project_assessment_item_id IS NOT NULL;"
    )
    _exec("CREATE INDEX idx_ai_suggestions_status ON ai_suggestions(status);")
    _exec(
        "CREATE INDEX idx_ai_suggestions_suggested_value_gin ON ai_suggestions USING gin(suggested_value);"
    )
    _exec("CREATE INDEX idx_ai_suggestions_metadata_gin ON ai_suggestions USING gin(metadata);")

    # --- assessment_instances ---
    _exec("CREATE INDEX idx_assessment_instances_project ON assessment_instances(project_id);")
    _exec("CREATE INDEX idx_assessment_instances_article ON assessment_instances(article_id);")
    _exec(
        "CREATE INDEX idx_assessment_instances_instrument ON assessment_instances(instrument_id) WHERE instrument_id IS NOT NULL;"
    )
    _exec(
        "CREATE INDEX idx_assessment_instances_project_instrument_id ON assessment_instances(project_instrument_id) WHERE project_instrument_id IS NOT NULL;"
    )
    _exec(
        "CREATE INDEX idx_assessment_instances_extraction ON assessment_instances(extraction_instance_id) WHERE extraction_instance_id IS NOT NULL;"
    )
    _exec("CREATE INDEX idx_assessment_instances_reviewer ON assessment_instances(reviewer_id);")
    _exec(
        "CREATE INDEX idx_assessment_instances_parent ON assessment_instances(parent_instance_id) WHERE parent_instance_id IS NOT NULL;"
    )
    _exec("CREATE INDEX idx_assessment_instances_status ON assessment_instances(status);")

    # --- assessment_responses ---
    _exec("CREATE INDEX idx_assessment_responses_project ON assessment_responses(project_id);")
    _exec("CREATE INDEX idx_assessment_responses_article ON assessment_responses(article_id);")
    _exec(
        "CREATE INDEX idx_assessment_responses_instance ON assessment_responses(assessment_instance_id);"
    )
    _exec("CREATE INDEX idx_assessment_responses_item ON assessment_responses(assessment_item_id);")
    _exec("CREATE INDEX idx_assessment_responses_reviewer ON assessment_responses(reviewer_id);")
    _exec("CREATE INDEX idx_assessment_responses_source ON assessment_responses(source);")
    _exec("CREATE INDEX idx_assessment_responses_level ON assessment_responses(selected_level);")

    # --- assessment_evidence ---
    _exec("CREATE INDEX idx_assessment_evidence_project ON assessment_evidence(project_id);")
    _exec("CREATE INDEX idx_assessment_evidence_article ON assessment_evidence(article_id);")
    _exec(
        "CREATE INDEX idx_assessment_evidence_target ON assessment_evidence(target_type, target_id);"
    )

    # --- user_api_keys ---
    _exec("CREATE INDEX idx_user_api_keys_user_id ON user_api_keys(user_id);")
    _exec("CREATE INDEX idx_user_api_keys_provider ON user_api_keys(provider);")

    _exec("""
          CREATE UNIQUE INDEX uq_assessment_instance_article_reviewer
              ON assessment_instances (project_id, article_id, reviewer_id) WHERE parent_instance_id IS NULL;
          """)

    # -----------------------------------------------------------------------
    # 6. ROW LEVEL SECURITY
    # -----------------------------------------------------------------------

    for tbl in [
        "profiles",
        "projects",
        "project_members",
        "articles",
        "article_files",
        "article_highlights",
        "article_boxes",
        "article_annotations",
        "extraction_templates_global",
        "project_extraction_templates",
        "extraction_entity_types",
        "extraction_fields",
        "extraction_instances",
        "extracted_values",
        "extraction_evidence",
        "extraction_runs",
        "ai_suggestions",
        "assessment_instruments",
        "assessment_items",
        "ai_assessment_configs",
        "ai_assessment_prompts",
        "ai_assessments",
        "ai_assessment_runs",
        "project_assessment_instruments",
        "project_assessment_items",
        "assessment_instances",
        "assessment_responses",
        "assessment_evidence",
        "zotero_integrations",
        "feedback_reports",
        "user_api_keys",
    ]:
        _exec(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")

    # --- profiles ---
    _exec("""
        CREATE POLICY "Users can view own profile"
          ON profiles FOR SELECT USING (auth.uid() = id);
        CREATE POLICY "Users can update own profile"
          ON profiles FOR UPDATE USING (auth.uid() = id);
    """)

    # --- projects ---
    _exec("""
        CREATE POLICY "project_select"
          ON projects FOR SELECT
          USING (
            EXISTS (SELECT 1 FROM project_members WHERE project_id = projects.id AND user_id = auth.uid())
          );
        CREATE POLICY "project_insert"
          ON projects FOR INSERT
          WITH CHECK (auth.uid() = created_by_id);
        CREATE POLICY "project_update"
          ON projects FOR UPDATE
          USING (is_project_manager(id, auth.uid()));
        CREATE POLICY "project_delete"
          ON projects FOR DELETE
          USING (is_project_manager(id, auth.uid()));
    """)

    # --- project_members ---
    _exec("""
        CREATE POLICY "project_members_select"
          ON project_members FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "project_members_insert"
          ON project_members FOR INSERT
          WITH CHECK (is_project_manager(project_id, auth.uid()));
        CREATE POLICY "project_members_update"
          ON project_members FOR UPDATE
          USING (is_project_manager(project_id, auth.uid()));
        CREATE POLICY "project_members_delete"
          ON project_members FOR DELETE
          USING (is_project_manager(project_id, auth.uid()));
    """)

    # --- articles ---
    _exec("""
        CREATE POLICY "articles_select"
          ON articles FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "articles_insert"
          ON articles FOR INSERT
          WITH CHECK (is_project_member(project_id, auth.uid()));
        CREATE POLICY "articles_update"
          ON articles FOR UPDATE
          USING (is_project_member(project_id, auth.uid()))
          WITH CHECK (is_project_member(project_id, auth.uid()));
        CREATE POLICY "articles_delete"
          ON articles FOR DELETE
          USING (is_project_manager(project_id, auth.uid()));
    """)

    # --- article_files --- (uses project_id directly for efficient RLS)
    _exec("""
        CREATE POLICY "article_files_select"
          ON article_files FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "article_files_insert"
          ON article_files FOR INSERT
          WITH CHECK (is_project_member(project_id, auth.uid()));
        CREATE POLICY "article_files_update"
          ON article_files FOR UPDATE
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "article_files_delete"
          ON article_files FOR DELETE
          USING (is_project_member(project_id, auth.uid()));
    """)

    # --- article_highlights / boxes / annotations ---
    for tbl in ("article_highlights", "article_boxes", "article_annotations"):
        _exec(f"""
            CREATE POLICY "{tbl}_select"
              ON {tbl} FOR SELECT
              USING (EXISTS (SELECT 1 FROM articles WHERE articles.id = {tbl}.article_id AND is_project_member(articles.project_id, auth.uid())));
            CREATE POLICY "{tbl}_insert"
              ON {tbl} FOR INSERT
              WITH CHECK (EXISTS (SELECT 1 FROM articles WHERE articles.id = {tbl}.article_id AND is_project_member(articles.project_id, auth.uid())));
            CREATE POLICY "{tbl}_update"
              ON {tbl} FOR UPDATE
              USING (EXISTS (SELECT 1 FROM articles WHERE articles.id = {tbl}.article_id AND is_project_member(articles.project_id, auth.uid())));
            CREATE POLICY "{tbl}_delete"
              ON {tbl} FOR DELETE
              USING (EXISTS (SELECT 1 FROM articles WHERE articles.id = {tbl}.article_id AND is_project_member(articles.project_id, auth.uid())));
        """)

    # --- extraction_templates_global (public read) ---
    _exec("""
        CREATE POLICY "extraction_templates_global_select"
          ON extraction_templates_global FOR SELECT USING (true);
        CREATE POLICY "extraction_templates_global_insert"
          ON extraction_templates_global FOR INSERT
          WITH CHECK (auth.role() = 'service_role');
        CREATE POLICY "extraction_templates_global_update"
          ON extraction_templates_global FOR UPDATE
          USING (auth.role() = 'service_role');
    """)

    # --- project_extraction_templates ---
    _exec("""
        CREATE POLICY "project_extraction_templates_select"
          ON project_extraction_templates FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "project_extraction_templates_insert"
          ON project_extraction_templates FOR INSERT
          WITH CHECK (is_project_manager(project_id, auth.uid()));
        CREATE POLICY "project_extraction_templates_update"
          ON project_extraction_templates FOR UPDATE
          USING (is_project_manager(project_id, auth.uid()));
        CREATE POLICY "project_extraction_templates_delete"
          ON project_extraction_templates FOR DELETE
          USING (is_project_manager(project_id, auth.uid()));
    """)

    # --- extraction_entity_types (public read + project write) ---
    _exec("""
        CREATE POLICY "extraction_entity_types_select"
          ON extraction_entity_types FOR SELECT USING (true);
        CREATE POLICY "extraction_entity_types_project_insert"
          ON extraction_entity_types FOR INSERT
          WITH CHECK (
            project_template_id IS NOT NULL AND
            EXISTS (
              SELECT 1 FROM project_extraction_templates pet
              WHERE pet.id = project_template_id
                AND is_project_member(pet.project_id, auth.uid())
            )
          );
        CREATE POLICY "extraction_entity_types_project_update"
          ON extraction_entity_types FOR UPDATE
          USING (
            project_template_id IS NOT NULL AND
            EXISTS (
              SELECT 1 FROM project_extraction_templates pet
              WHERE pet.id = project_template_id
                AND is_project_member(pet.project_id, auth.uid())
            )
          );
        CREATE POLICY "extraction_entity_types_project_delete"
          ON extraction_entity_types FOR DELETE
          USING (
            project_template_id IS NOT NULL AND
            EXISTS (
              SELECT 1 FROM project_extraction_templates pet
              WHERE pet.id = project_template_id
                AND is_project_manager(pet.project_id, auth.uid())
            )
          );
    """)

    # --- extraction_fields (public read + project write) ---
    _exec("""
        CREATE POLICY "extraction_fields_select"
          ON extraction_fields FOR SELECT USING (true);
        CREATE POLICY "extraction_fields_project_insert"
          ON extraction_fields FOR INSERT
          WITH CHECK (
            EXISTS (
              SELECT 1 FROM extraction_entity_types et
              JOIN project_extraction_templates pet ON pet.id = et.project_template_id
              WHERE et.id = entity_type_id
                AND is_project_member(pet.project_id, auth.uid())
            )
          );
        CREATE POLICY "extraction_fields_project_update"
          ON extraction_fields FOR UPDATE
          USING (
            EXISTS (
              SELECT 1 FROM extraction_entity_types et
              JOIN project_extraction_templates pet ON pet.id = et.project_template_id
              WHERE et.id = entity_type_id
                AND is_project_member(pet.project_id, auth.uid())
            )
          );
        CREATE POLICY "extraction_fields_project_delete"
          ON extraction_fields FOR DELETE
          USING (
            EXISTS (
              SELECT 1 FROM extraction_entity_types et
              JOIN project_extraction_templates pet ON pet.id = et.project_template_id
              WHERE et.id = entity_type_id
                AND is_project_manager(pet.project_id, auth.uid())
            )
          );
    """)

    # --- extraction_instances ---
    _exec("""
        CREATE POLICY "extraction_instances_select"
          ON extraction_instances FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "extraction_instances_insert"
          ON extraction_instances FOR INSERT
          WITH CHECK (is_project_member(project_id, auth.uid()));
        CREATE POLICY "extraction_instances_update"
          ON extraction_instances FOR UPDATE
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "extraction_instances_delete"
          ON extraction_instances FOR DELETE
          USING (is_project_manager(project_id, auth.uid()));
    """)

    # --- extracted_values ---
    _exec("""
        CREATE POLICY "extracted_values_select"
          ON extracted_values FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "extracted_values_insert"
          ON extracted_values FOR INSERT
          WITH CHECK (is_project_member(project_id, auth.uid()));
        CREATE POLICY "extracted_values_update"
          ON extracted_values FOR UPDATE
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "extracted_values_delete"
          ON extracted_values FOR DELETE
          USING (is_project_member(project_id, auth.uid()));
    """)

    # --- extraction_evidence ---
    _exec("""
        CREATE POLICY "extraction_evidence_select"
          ON extraction_evidence FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "extraction_evidence_insert"
          ON extraction_evidence FOR INSERT
          WITH CHECK (is_project_member(project_id, auth.uid()));
        CREATE POLICY "extraction_evidence_delete"
          ON extraction_evidence FOR DELETE
          USING (is_project_member(project_id, auth.uid()));
    """)

    # --- extraction_runs ---
    _exec("""
        CREATE POLICY "extraction_runs_select"
          ON extraction_runs FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "extraction_runs_insert"
          ON extraction_runs FOR INSERT
          WITH CHECK (is_project_member(project_id, auth.uid()));
        CREATE POLICY "extraction_runs_update"
          ON extraction_runs FOR UPDATE
          USING (is_project_member(project_id, auth.uid()));
    """)

    # --- ai_suggestions (final RLS from 0036) ---
    _exec("""
        CREATE POLICY "ai_suggestions_read_by_project_members"
          ON ai_suggestions FOR SELECT
          USING (
            EXISTS (
              SELECT 1 FROM extraction_runs er
              JOIN project_members pm ON pm.project_id = er.project_id
              WHERE er.id = ai_suggestions.extraction_run_id
                AND pm.user_id = auth.uid()
            )
            OR
            EXISTS (
              SELECT 1 FROM ai_assessment_runs aar
              JOIN project_members pm ON pm.project_id = aar.project_id
              WHERE aar.id = ai_suggestions.assessment_run_id
                AND pm.user_id = auth.uid()
            )
          );
        CREATE POLICY "ai_suggestions_insert_by_project_members"
          ON ai_suggestions FOR INSERT
          WITH CHECK (auth.role() = 'service_role');
        CREATE POLICY "ai_suggestions_update_by_project_members"
          ON ai_suggestions FOR UPDATE
          USING (
            EXISTS (
              SELECT 1 FROM extraction_runs er
              JOIN project_members pm ON pm.project_id = er.project_id
              WHERE er.id = ai_suggestions.extraction_run_id
                AND pm.user_id = auth.uid()
            )
            OR
            EXISTS (
              SELECT 1 FROM ai_assessment_runs aar
              JOIN project_members pm ON pm.project_id = aar.project_id
              WHERE aar.id = ai_suggestions.assessment_run_id
                AND pm.user_id = auth.uid()
            )
          );
        CREATE POLICY "ai_suggestions_delete_by_project_members"
          ON ai_suggestions FOR DELETE
          USING (auth.role() = 'service_role');
    """)

    # --- assessment_instruments (public read) ---
    _exec("""
        CREATE POLICY "assessment_instruments_select"
          ON assessment_instruments FOR SELECT USING (true);
    """)

    # --- assessment_items (public read) ---
    _exec("""
        CREATE POLICY "assessment_items_select"
          ON assessment_items FOR SELECT USING (true);
    """)

    # --- ai_assessment_configs ---
    _exec("""
        CREATE POLICY "ai_assessment_configs_select"
          ON ai_assessment_configs FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "ai_assessment_configs_insert"
          ON ai_assessment_configs FOR INSERT
          WITH CHECK (is_project_manager(project_id, auth.uid()));
        CREATE POLICY "ai_assessment_configs_update"
          ON ai_assessment_configs FOR UPDATE
          USING (is_project_manager(project_id, auth.uid()));
    """)

    # --- ai_assessment_prompts ---
    _exec("""
        CREATE POLICY "ai_assessment_prompts_select"
          ON ai_assessment_prompts FOR SELECT USING (true);
    """)

    # --- ai_assessments ---
    _exec("""
        CREATE POLICY "ai_assessments_select"
          ON ai_assessments FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "ai_assessments_insert"
          ON ai_assessments FOR INSERT
          WITH CHECK (auth.role() = 'service_role');
        CREATE POLICY "ai_assessments_update"
          ON ai_assessments FOR UPDATE
          USING (auth.role() = 'service_role');
    """)

    # --- ai_assessment_runs ---
    _exec("""
        CREATE POLICY ai_assessment_runs_select_policy
          ON ai_assessment_runs FOR SELECT
          USING (EXISTS (SELECT 1 FROM project_members WHERE project_members.project_id = ai_assessment_runs.project_id AND project_members.user_id = auth.uid()));
        CREATE POLICY ai_assessment_runs_insert_policy
          ON ai_assessment_runs FOR INSERT
          WITH CHECK (
            EXISTS (SELECT 1 FROM project_members WHERE project_members.project_id = ai_assessment_runs.project_id AND project_members.user_id = auth.uid())
            AND created_by = auth.uid()
          );
        CREATE POLICY ai_assessment_runs_update_policy
          ON ai_assessment_runs FOR UPDATE
          USING (
            EXISTS (
              SELECT 1 FROM project_members
              WHERE project_members.project_id = ai_assessment_runs.project_id
                AND project_members.user_id = auth.uid()
                AND (ai_assessment_runs.created_by = auth.uid() OR project_members.role = 'manager')
            )
          );
    """)

    # --- project_assessment_instruments ---
    _exec("""
        CREATE POLICY "Users can view project instruments"
          ON project_assessment_instruments FOR SELECT
          USING (project_id IN (SELECT project_id FROM project_members WHERE user_id = auth.uid()));
        CREATE POLICY "Users can insert project instruments"
          ON project_assessment_instruments FOR INSERT
          WITH CHECK (project_id IN (SELECT project_id FROM project_members WHERE user_id = auth.uid()));
        CREATE POLICY "Users can update project instruments"
          ON project_assessment_instruments FOR UPDATE
          USING (project_id IN (SELECT project_id FROM project_members WHERE user_id = auth.uid()));
        CREATE POLICY "Users can delete project instruments"
          ON project_assessment_instruments FOR DELETE
          USING (project_id IN (SELECT project_id FROM project_members WHERE user_id = auth.uid()));
        CREATE POLICY "Service role has full access to project instruments"
          ON project_assessment_instruments FOR ALL TO service_role
          USING (true) WITH CHECK (true);
    """)

    # --- project_assessment_items ---
    _exec("""
        CREATE POLICY "Users can view project items"
          ON project_assessment_items FOR SELECT
          USING (project_instrument_id IN (SELECT pai.id FROM project_assessment_instruments pai JOIN project_members pm ON pm.project_id = pai.project_id WHERE pm.user_id = auth.uid()));
        CREATE POLICY "Users can insert project items"
          ON project_assessment_items FOR INSERT
          WITH CHECK (project_instrument_id IN (SELECT pai.id FROM project_assessment_instruments pai JOIN project_members pm ON pm.project_id = pai.project_id WHERE pm.user_id = auth.uid()));
        CREATE POLICY "Users can update project items"
          ON project_assessment_items FOR UPDATE
          USING (project_instrument_id IN (SELECT pai.id FROM project_assessment_instruments pai JOIN project_members pm ON pm.project_id = pai.project_id WHERE pm.user_id = auth.uid()));
        CREATE POLICY "Users can delete project items"
          ON project_assessment_items FOR DELETE
          USING (project_instrument_id IN (SELECT pai.id FROM project_assessment_instruments pai JOIN project_members pm ON pm.project_id = pai.project_id WHERE pm.user_id = auth.uid()));
        CREATE POLICY "Service role has full access to project items"
          ON project_assessment_items FOR ALL TO service_role
          USING (true) WITH CHECK (true);
    """)

    # --- assessment_instances ---
    _exec("""
        CREATE POLICY "Members can view assessment instances"
          ON assessment_instances FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "Members can manage assessment instances"
          ON assessment_instances FOR ALL
          USING (is_project_member(project_id, auth.uid()));
    """)

    # --- assessment_responses ---
    _exec("""
        CREATE POLICY "Members can view assessment responses"
          ON assessment_responses FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "Members can manage assessment responses"
          ON assessment_responses FOR ALL
          USING (is_project_member(project_id, auth.uid()));
    """)

    # --- assessment_evidence ---
    _exec("""
        CREATE POLICY "Members can view assessment evidence"
          ON assessment_evidence FOR SELECT
          USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "Members can manage assessment evidence"
          ON assessment_evidence FOR ALL
          USING (is_project_member(project_id, auth.uid()));
    """)

    # --- zotero_integrations ---
    _exec("""
        CREATE POLICY "zotero_integrations_select"
          ON zotero_integrations FOR SELECT
          USING (user_id = auth.uid());
        CREATE POLICY "zotero_integrations_insert"
          ON zotero_integrations FOR INSERT
          WITH CHECK (user_id = auth.uid());
        CREATE POLICY "zotero_integrations_update"
          ON zotero_integrations FOR UPDATE
          USING (user_id = auth.uid());
        CREATE POLICY "zotero_integrations_delete"
          ON zotero_integrations FOR DELETE
          USING (user_id = auth.uid());
    """)

    # --- feedback_reports ---
    _exec("""
        CREATE POLICY "feedback_reports_insert"
          ON feedback_reports FOR INSERT WITH CHECK (true);
        CREATE POLICY "feedback_reports_select_own"
          ON feedback_reports FOR SELECT
          USING (user_id = auth.uid() OR auth.role() = 'service_role');
    """)

    # --- user_api_keys ---
    _exec("""
        CREATE POLICY "user_api_keys_select"
          ON user_api_keys FOR SELECT USING (user_id = auth.uid());
        CREATE POLICY "user_api_keys_insert"
          ON user_api_keys FOR INSERT WITH CHECK (user_id = auth.uid());
        CREATE POLICY "user_api_keys_update"
          ON user_api_keys FOR UPDATE USING (user_id = auth.uid());
        CREATE POLICY "user_api_keys_delete"
          ON user_api_keys FOR DELETE USING (user_id = auth.uid());
    """)

    # -----------------------------------------------------------------------
    # 7. TRIGGER FUNCTIONS AND TRIGGERS
    # -----------------------------------------------------------------------

    # updated_at triggers for each table that has updated_at column
    # Note: tables using UUIDMixin only (no TimestampMixin) are excluded:
    #   assessment_instruments, assessment_items, extraction_runs, ai_suggestions
    for tbl in [
        "profiles",
        "projects",
        "project_members",
        "articles",
        "article_files",
        "article_annotations",
        "extraction_templates_global",
        "project_extraction_templates",
        "extraction_entity_types",
        "extraction_fields",
        "extraction_instances",
        "extracted_values",
        "extraction_evidence",
        "ai_assessment_configs",
        "ai_assessment_prompts",
        "ai_assessments",
        "ai_assessment_runs",
        "project_assessment_instruments",
        "project_assessment_items",
        "assessment_instances",
        "assessment_responses",
        "assessment_evidence",
        "zotero_integrations",
        "feedback_reports",
        "user_api_keys",
    ]:
        _exec(f"""
            CREATE TRIGGER trg_{tbl}_updated_at
              BEFORE UPDATE ON {tbl}
              FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
        """)

    # --- extraction instance hierarchy validation (from 0016) ---------------
    _exec("""
          CREATE
          OR REPLACE FUNCTION validate_extraction_instance_hierarchy()
        RETURNS TRIGGER AS $$
        DECLARE
          v_parent extraction_instances
          %ROWTYPE;
          BEGIN
            IF
          NEW.parent_instance_id IS NULL THEN
                RETURN NEW;
          END IF;
          SELECT *
          INTO v_parent
          FROM extraction_instances
          WHERE id = NEW.parent_instance_id;
          IF
          NOT FOUND THEN
                RAISE EXCEPTION 'Parent instance % not found', NEW.parent_instance_id;
          END IF;
            IF
          v_parent.project_id != NEW.project_id THEN
                RAISE EXCEPTION 'Parent and child must belong to the same project';
          END IF;
            IF
          v_parent.article_id IS DISTINCT FROM NEW.article_id THEN
                RAISE EXCEPTION 'Parent and child must belong to the same article';
          END IF;
          RETURN NEW;
          END;
        $$
          LANGUAGE plpgsql;
          """)
    _exec("""
          CREATE TRIGGER trg_validate_extraction_hierarchy
              BEFORE INSERT OR
          UPDATE OF parent_instance_id, project_id, article_id
          ON extraction_instances
              FOR EACH ROW EXECUTE FUNCTION validate_extraction_instance_hierarchy();
          """)

    # --- instance project consistency (from 0018) ---------------------------
    _exec("""
          CREATE
          OR REPLACE FUNCTION validate_instance_project_consistency()
        RETURNS TRIGGER AS $$
          BEGIN
            IF
          NOT EXISTS (
                SELECT 1 FROM projects
                WHERE id = NEW.project_id
            ) THEN
                RAISE EXCEPTION 'Project % does not exist', NEW.project_id;
          END IF;
          RETURN NEW;
          END;
        $$
          LANGUAGE plpgsql;
          """)

    # --- assessment instance hierarchy validation (from 0030) ---------------
    _exec("""
          CREATE
          OR REPLACE FUNCTION validate_assessment_instance_hierarchy()
        RETURNS TRIGGER AS $$
        DECLARE
          v_parent assessment_instances
          %ROWTYPE;
          BEGIN
            IF
          NEW.parent_instance_id IS NULL THEN
                RETURN NEW;
          END IF;
          SELECT *
          INTO v_parent
          FROM assessment_instances
          WHERE id = NEW.parent_instance_id;
          IF
          NOT FOUND THEN
                RAISE EXCEPTION 'Parent instance % not found', NEW.parent_instance_id;
          END IF;
            IF
          v_parent.project_id != NEW.project_id THEN
                RAISE EXCEPTION 'Parent and child assessment instances must belong to the same project';
          END IF;
            IF
          v_parent.article_id != NEW.article_id THEN
                RAISE EXCEPTION 'Parent and child assessment instances must belong to the same article';
          END IF;
            IF
          v_parent.instrument_id IS DISTINCT FROM NEW.instrument_id THEN
                RAISE EXCEPTION 'Parent and child assessment instances must use the same instrument_id';
          END IF;
            IF
          v_parent.extraction_instance_id IS DISTINCT FROM NEW.extraction_instance_id THEN
                RAISE EXCEPTION 'Child must have same extraction_instance_id as parent';
          END IF;
            IF
          EXISTS (
                WITH RECURSIVE hierarchy AS (
                    SELECT id, parent_instance_id, 1 as depth
                    FROM assessment_instances WHERE id = NEW.parent_instance_id
                    UNION ALL
                    SELECT ai.id, ai.parent_instance_id, h.depth + 1
                    FROM assessment_instances ai
                    JOIN hierarchy h ON ai.id = h.parent_instance_id
                    WHERE h.depth < 10 AND ai.id != COALESCE(NEW.id, '00000000-0000-0000-0000-000000000000'::uuid)
                )
                SELECT 1 FROM hierarchy WHERE parent_instance_id = NEW.id LIMIT 1
            ) THEN
                RAISE EXCEPTION 'Cycle detected in assessment instance hierarchy';
          END IF;
          RETURN NEW;
          END;
        $$
          LANGUAGE plpgsql;
          """)
    _exec("""
          CREATE TRIGGER trg_validate_assessment_hierarchy
              BEFORE INSERT OR
          UPDATE OF parent_instance_id, project_id, article_id, instrument_id, extraction_instance_id
          ON assessment_instances
              FOR EACH ROW EXECUTE FUNCTION validate_assessment_instance_hierarchy();
          """)

    # --- single default API key (from 0022) ---------------------------------
    _exec("""
          CREATE
          OR REPLACE FUNCTION ensure_single_default_api_key()
        RETURNS TRIGGER AS $$
          BEGIN
            IF
          NEW.is_default THEN
          UPDATE user_api_keys
          SET is_default = false
          WHERE user_id = NEW.user_id
            AND provider = NEW.provider
            AND id != NEW.id;
          END IF;
          RETURN NEW;
          END;
        $$
          LANGUAGE plpgsql;
          """)
    _exec("""
          CREATE TRIGGER trg_ensure_single_default_api_key
              BEFORE INSERT OR
          UPDATE OF is_default
          ON user_api_keys
              FOR EACH ROW EXECUTE FUNCTION ensure_single_default_api_key();
          """)

    # -----------------------------------------------------------------------
    # 8. FUNCTIONS THAT DEPEND ON TABLES
    # -----------------------------------------------------------------------

    # calculate_model_progress (from 0021)
    _exec("""
          CREATE
          OR REPLACE FUNCTION calculate_model_progress(p_project_id uuid, p_article_id uuid)
        RETURNS TABLE (
            extraction_instance_id  uuid,
            entity_type_name        character varying,
            total_fields            integer,
            filled_fields           integer,
            completion_percentage   numeric(5,2)
        ) AS $$
          BEGIN
          RETURN QUERY
          SELECT ei.id   AS extraction_instance_id,
                 et.name AS entity_type_name,
                 COUNT(ef.id)::integer AS total_fields, COUNT(ev.id)::integer AS filled_fields, CASE
                                                                                                    WHEN COUNT(ef.id) = 0
                                                                                                        THEN 0::numeric(5,2)
                    ELSE ROUND((COUNT(ev.id)::numeric / COUNT(ef.id)::numeric) * 100, 2)
          END
          AS completion_percentage
            FROM extraction_instances ei
            JOIN extraction_entity_types et ON et.id = ei.entity_type_id
            JOIN extraction_fields ef ON ef.entity_type_id = et.id
            LEFT JOIN extracted_values ev ON ev.instance_id = ei.id AND ev.field_id = ef.id
            WHERE ei.project_id = p_project_id
              AND ei.article_id = p_article_id
            GROUP BY ei.id, et.name;
          END;
        $$
          LANGUAGE plpgsql STABLE;
          """)

    # calculate_assessment_instance_progress (final state from 20260218)
    _exec("""
          CREATE
          OR REPLACE FUNCTION calculate_assessment_instance_progress(p_instance_id UUID)
        RETURNS TABLE (
            total_items             INTEGER,
            answered_items          INTEGER,
            completion_percentage   NUMERIC(5,2)
        ) AS $$
          BEGIN
          RETURN QUERY WITH instance_info AS (
                SELECT
                    ai_inst.instrument_id AS global_instrument_id,
                    ai_inst.project_instrument_id
                FROM assessment_instances ai_inst
                WHERE ai_inst.id = p_instance_id
            ),
            total AS (
                SELECT COUNT(*) as total_count
                FROM (
                    SELECT gi.id
                    FROM assessment_items gi
                    WHERE gi.instrument_id = (SELECT global_instrument_id FROM instance_info)
                      AND gi.required = true
                      AND (SELECT global_instrument_id FROM instance_info) IS NOT NULL
                    UNION ALL
                    SELECT pi.id
                    FROM project_assessment_items pi
                    WHERE pi.project_instrument_id = (SELECT project_instrument_id FROM instance_info)
                      AND pi.required = true
                      AND (SELECT project_instrument_id FROM instance_info) IS NOT NULL
                ) combined_items
            ),
            answered AS (
                SELECT COUNT(DISTINCT ar.assessment_item_id) as answered_count
                FROM assessment_responses ar
                WHERE ar.assessment_instance_id = p_instance_id
            )
          SELECT total.total_count::INTEGER, answered.answered_count::INTEGER, CASE
                                                                                   WHEN total.total_count = 0 THEN 0::NUMERIC(5,2)
                    ELSE ROUND((answered.answered_count::NUMERIC / total.total_count::NUMERIC) * 100, 2)
          END
          FROM total, answered;
          END;
        $$
          LANGUAGE plpgsql STABLE;
          """)

    # get_assessment_instance_children (from 0030)
    _exec("""
          CREATE
          OR REPLACE FUNCTION get_assessment_instance_children(p_instance_id UUID)
        RETURNS TABLE (
            id          UUID,
            label       VARCHAR,
            status      assessment_status,
            reviewer_id UUID,
            created_at  TIMESTAMPTZ,
            updated_at  TIMESTAMPTZ
        ) AS $$
          BEGIN
          RETURN QUERY
          SELECT ai.id, ai.label, ai.status, ai.reviewer_id, ai.created_at, ai.updated_at
          FROM assessment_instances ai
          WHERE ai.parent_instance_id = p_instance_id
          ORDER BY ai.created_at;
          END;
        $$
          LANGUAGE plpgsql STABLE;
          """)

    # create_project_with_member (from 0023)
    _exec("""
          CREATE
          OR REPLACE FUNCTION create_project_with_member(
            p_name          text,
            p_description   text DEFAULT NULL,
            p_review_type   review_type DEFAULT 'other',
            p_created_by    uuid DEFAULT auth.uid()
        )
        RETURNS uuid AS $$
        DECLARE
          v_project_id uuid;
          BEGIN
          INSERT INTO projects (name, description, review_type, created_by_id)
          VALUES (p_name, p_description, p_review_type, p_created_by) RETURNING id
          INTO v_project_id;

          INSERT INTO project_members (project_id, user_id, role)
          VALUES (v_project_id, p_created_by, 'manager');

          RETURN v_project_id;
          END;
        $$
          LANGUAGE plpgsql SECURITY DEFINER;
          """)

    # find_user_id_by_email (from 0025)
    _exec("""
          CREATE
          OR REPLACE FUNCTION find_user_id_by_email(p_email text)
        RETURNS uuid AS $$
          BEGIN
          RETURN (SELECT id
                  FROM auth.users
                  WHERE email = p_email LIMIT 1);
          END;
        $$
          LANGUAGE plpgsql SECURITY DEFINER;
          """)

    # get_project_members (from 0025/0026) — column names fixed in 0002
    _exec("""
          CREATE
          OR REPLACE FUNCTION get_project_members(p_project_id uuid)
        RETURNS TABLE (
            id              uuid,
            user_id         uuid,
            role            project_member_role,
            permissions     jsonb,
            created_at      timestamptz,
            user_email      text,
            user_full_name  text,
            user_avatar_url text
        ) AS $$
          BEGIN
          RETURN QUERY
          SELECT pm.id,
                 pm.user_id,
                 pm.role,
                 pm.permissions,
                 pm.created_at,
                 u.email      AS user_email,
                 p.full_name  AS user_full_name,
                 p.avatar_url AS user_avatar_url
          FROM project_members pm
                   JOIN auth.users u ON u.id = pm.user_id
                   LEFT JOIN profiles p ON p.id = pm.user_id
          WHERE pm.project_id = p_project_id;
          END;
        $$
          LANGUAGE plpgsql SECURITY DEFINER;
          """)

    # clone_global_instrument_to_project (from 0034)
    _exec("""
          CREATE
          OR REPLACE FUNCTION clone_global_instrument_to_project(
            p_project_id            uuid,
            p_global_instrument_id  uuid,
            p_created_by            uuid,
            p_custom_name           text DEFAULT NULL
        )
        RETURNS uuid AS $$
        DECLARE
          v_new_instrument_id uuid;
            v_instrument_record
          RECORD;
            v_item_record
          RECORD;
          BEGIN
          SELECT *
          INTO v_instrument_record
          FROM assessment_instruments
          WHERE id = p_global_instrument_id;
          IF
          NOT FOUND THEN
                RAISE EXCEPTION 'Global instrument not found: %', p_global_instrument_id;
          END IF;

          INSERT INTO project_assessment_instruments (project_id, global_instrument_id, name, description, tool_type,
                                                      version,
                                                      mode, is_active, aggregation_rules, schema, created_by)
          VALUES (p_project_id, p_global_instrument_id,
                  COALESCE(p_custom_name, v_instrument_record.name),
                  v_instrument_record.schema ->>'description',
                  v_instrument_record.tool_type, v_instrument_record.version,
                  v_instrument_record.mode, true,
                  v_instrument_record.aggregation_rules, v_instrument_record.schema,
                  p_created_by) RETURNING id
          INTO v_new_instrument_id;

          FOR v_item_record IN
          SELECT *
          FROM assessment_items
          WHERE instrument_id = p_global_instrument_id
          ORDER BY sort_order
              LOOP
          INSERT
          INTO project_assessment_items (project_instrument_id, global_item_id, domain, item_code, question,
                                         description, sort_order, required, allowed_levels, llm_prompt)
          VALUES (
              v_new_instrument_id, v_item_record.id, v_item_record.domain, v_item_record.item_code, v_item_record.question, v_item_record.description, v_item_record.sort_order, v_item_record.required, v_item_record.allowed_levels, v_item_record.llm_prompt
              );
          END LOOP;

          RETURN v_new_instrument_id;
          END;
        $$
          LANGUAGE plpgsql SECURITY DEFINER;
          """)

    # -----------------------------------------------------------------------
    # 9. ASSESSMENTS COMPATIBILITY VIEW (final state from 20260218)
    # -----------------------------------------------------------------------

    _exec("""
          CREATE
          OR REPLACE VIEW assessments WITH (security_invoker=true) AS
          SELECT ai.id,
                 ai.project_id,
                 ai.article_id,
                 ai.reviewer_id                                       AS user_id,
                 COALESCE(gi.tool_type, pi.tool_type)                 AS tool_type,
                 COALESCE(ai.instrument_id, ai.project_instrument_id) AS instrument_id,
                 ai.extraction_instance_id,
                 COALESCE(
                         (SELECT jsonb_object_agg(
                                         ar.assessment_item_id::text,
                                         jsonb_build_object(
                                                 'item_id', ar.assessment_item_id,
                                                 'selected_level', ar.selected_level,
                                                 'notes', ar.notes,
                                                 'confidence', ar.confidence,
                                                 'source', ar.source::text,
                                                 'ai_suggestion_id', ar.ai_suggestion_id
                                         )
                                 )
                          FROM assessment_responses ar
                          WHERE ar.assessment_instance_id = ai.id),
                         '{}' ::jsonb
                 )                                                    AS responses,
                 CASE
                     WHEN ai.metadata ? 'overall_risk' OR ai.metadata    ? 'summary' THEN
                    jsonb_build_object(
                        'overall_risk', ai.metadata->>'overall_risk',
                        'summary', ai.metadata->>'summary',
                        'applicability', ai.metadata->>'applicability'
                    )
                ELSE NULL
          END
          AS overall_assessment,
            NULL::integer AS confidence_level,
            ai.status,
            (
                SELECT completion_percentage
                FROM calculate_assessment_instance_progress(ai.id)
                LIMIT 1
            ) AS completion_percentage,
            1 AS version,
            true AS is_current_version,
            NULL::uuid AS parent_assessment_id,
            ai.is_blind,
            ai.can_see_others,
            COALESCE(ai.metadata->'comments', '[]'::jsonb) AS comments,
            ai.metadata->>'private_notes' AS private_notes,
            CASE
                WHEN EXISTS (
                    SELECT 1 FROM assessment_responses ar
                    WHERE ar.assessment_instance_id = ai.id AND ar.source = 'ai'
                ) THEN 'ai'
                ELSE 'human'
          END
          AS assessed_by_type,
            NULL::uuid AS run_id,
            1 AS row_version,
            ai.created_at,
            ai.updated_at
        FROM assessment_instances ai
        LEFT JOIN assessment_instruments gi ON gi.id = ai.instrument_id
        LEFT JOIN project_assessment_instruments pi ON pi.id = ai.project_instrument_id;

        COMMENT
          ON VIEW assessments IS
            'Compatibility view: aggregates assessment_responses into legacy JSONB format.
            Supports both global and project-scoped instruments via XOR pattern.
            Will be removed in v2.0.';
          """)

    # INSTEAD OF INSERT trigger (final state from 20260218)
    # Note: assessment_responses.assessment_item_id is now NOT NULL, referencing assessment_items only.
    # Project-instrument inserts via the view are only supported for global instruments.
    _exec("""
          CREATE
          OR REPLACE FUNCTION assessments_insert_trigger()
        RETURNS TRIGGER AS $$
        DECLARE
          v_instance_id           uuid;
            v_item
          RECORD;
            v_is_project_instrument
          boolean;
          BEGIN
          SELECT EXISTS (SELECT 1
                         FROM project_assessment_instruments
                         WHERE id = NEW.instrument_id)
          INTO v_is_project_instrument;

          IF
          v_is_project_instrument THEN
                INSERT INTO assessment_instances (
                    project_id, article_id, instrument_id, project_instrument_id,
                    extraction_instance_id, label, status, reviewer_id,
                    is_blind, can_see_others, metadata
                ) VALUES (
                    NEW.project_id, NEW.article_id, NULL, NEW.instrument_id,
                    NEW.extraction_instance_id,
                    COALESCE(NEW.tool_type || ' Assessment', 'Assessment'),
                    COALESCE(NEW.status, 'in_progress'), NEW.user_id,
                    COALESCE(NEW.is_blind, false), COALESCE(NEW.can_see_others, true),
                    jsonb_build_object(
                        'overall_assessment', NEW.overall_assessment,
                        'comments', COALESCE(NEW.comments, '[]'::jsonb),
                        'private_notes', NEW.private_notes
                    )
                ) RETURNING id INTO v_instance_id;

                -- For project instruments, insert responses via global item if available
          FOR v_item IN
          SELECT key AS item_key, value AS response_value
          FROM jsonb_each(COALESCE (NEW.responses, '{}'::jsonb))
              LOOP
          INSERT
          INTO assessment_responses (project_id, article_id, assessment_instance_id,
                                     assessment_item_id,
                                     selected_level, notes, confidence, source, reviewer_id)
          SELECT NEW.project_id,
                 NEW.article_id,
                 v_instance_id,
                 COALESCE(pai.global_item_id, pai.id),
                 v_item.response_value ->>'selected_level', v_item.response_value->>'notes', (v_item.response_value->>'confidence'):: numeric, COALESCE ((v_item.response_value->>'source')::assessment_source, 'human'), NEW.user_id
          FROM project_assessment_items pai
          WHERE (pai.id::text = v_item.item_key
             OR pai.item_code = v_item.item_key)
            AND pai.project_instrument_id = NEW.instrument_id
            AND pai.global_item_id IS NOT NULL;
          END LOOP;
          ELSE
                INSERT INTO assessment_instances (
                    project_id, article_id, instrument_id, project_instrument_id,
                    extraction_instance_id, label, status, reviewer_id,
                    is_blind, can_see_others, metadata
                ) VALUES (
                    NEW.project_id, NEW.article_id, NEW.instrument_id, NULL,
                    NEW.extraction_instance_id,
                    COALESCE(NEW.tool_type || ' Assessment', 'Assessment'),
                    COALESCE(NEW.status, 'in_progress'), NEW.user_id,
                    COALESCE(NEW.is_blind, false), COALESCE(NEW.can_see_others, true),
                    jsonb_build_object(
                        'overall_assessment', NEW.overall_assessment,
                        'comments', COALESCE(NEW.comments, '[]'::jsonb),
                        'private_notes', NEW.private_notes
                    )
                ) RETURNING id INTO v_instance_id;

          FOR v_item IN
          SELECT key AS item_key, value AS response_value
          FROM jsonb_each(COALESCE (NEW.responses, '{}'::jsonb))
              LOOP
          INSERT
          INTO assessment_responses (project_id, article_id, assessment_instance_id,
                                     assessment_item_id,
                                     selected_level, notes, confidence, source, reviewer_id)
          SELECT NEW.project_id,
                 NEW.article_id,
                 v_instance_id,
                 ai.id,
                 v_item.response_value ->>'selected_level', v_item.response_value->>'notes', (v_item.response_value->>'confidence'):: numeric, COALESCE ((v_item.response_value->>'source')::assessment_source, 'human'), NEW.user_id
          FROM assessment_items ai
          WHERE (ai.id::text = v_item.item_key
             OR ai.item_code = v_item.item_key)
            AND ai.instrument_id = NEW.instrument_id;
          END LOOP;
          END IF;

            NEW.id
          := v_instance_id;
          RETURN NEW;
          END;
        $$
          LANGUAGE plpgsql SECURITY DEFINER;
          """)
    _exec("""
          CREATE TRIGGER assessments_instead_of_insert
              INSTEAD OF INSERT
              ON assessments
              FOR EACH ROW EXECUTE FUNCTION assessments_insert_trigger();
          """)

    # INSTEAD OF UPDATE trigger (final state from 20260218)
    _exec("""
          CREATE
          OR REPLACE FUNCTION assessments_update_trigger()
        RETURNS TRIGGER AS $$
        DECLARE
          v_item                  RECORD;
            v_is_project_instrument
          boolean;
          BEGIN
          UPDATE assessment_instances
          SET status         = COALESCE(NEW.status, status),
              is_blind       = COALESCE(NEW.is_blind, is_blind),
              can_see_others = COALESCE(NEW.can_see_others, can_see_others),
              metadata       = metadata || jsonb_build_object(
                      'overall_assessment', NEW.overall_assessment,
                      'comments', COALESCE(NEW.comments, '[]'::jsonb),
                      'private_notes', NEW.private_notes
                                           ),
              updated_at     = NOW()
          WHERE id = OLD.id;

          IF
          NEW.responses IS NOT NULL AND NEW.responses != OLD.responses THEN
          SELECT (project_instrument_id IS NOT NULL)
          INTO v_is_project_instrument
          FROM assessment_instances
          WHERE id = OLD.id;

          DELETE
          FROM assessment_responses
          WHERE assessment_instance_id = OLD.id;

          IF
          v_is_project_instrument THEN
                    FOR v_item IN
          SELECT key AS item_key, value AS response_value
          FROM jsonb_each(NEW.responses)
              LOOP
          INSERT
          INTO assessment_responses (project_id, article_id, assessment_instance_id,
                                     assessment_item_id,
                                     selected_level, notes, confidence, source, reviewer_id)
          SELECT NEW.project_id,
                 NEW.article_id,
                 OLD.id,
                 COALESCE(pai.global_item_id, pai.id),
                 v_item.response_value ->>'selected_level', v_item.response_value->>'notes', (v_item.response_value->>'confidence'):: numeric, COALESCE ((v_item.response_value->>'source')::assessment_source, 'human'), NEW.user_id
          FROM project_assessment_items pai
          WHERE (pai.id::text = v_item.item_key
             OR pai.item_code = v_item.item_key)
            AND pai.project_instrument_id = (
              SELECT project_instrument_id FROM assessment_instances WHERE id = OLD.id
              )
            AND pai.global_item_id IS NOT NULL;
          END LOOP;
          ELSE
                    FOR v_item IN
          SELECT key AS item_key, value AS response_value
          FROM jsonb_each(NEW.responses)
              LOOP
          INSERT
          INTO assessment_responses (project_id, article_id, assessment_instance_id,
                                     assessment_item_id,
                                     selected_level, notes, confidence, source, reviewer_id)
          SELECT NEW.project_id,
                 NEW.article_id,
                 OLD.id,
                 ai.id,
                 v_item.response_value ->>'selected_level', v_item.response_value->>'notes', (v_item.response_value->>'confidence'):: numeric, COALESCE ((v_item.response_value->>'source')::assessment_source, 'human'), NEW.user_id
          FROM assessment_items ai
          WHERE (ai.id::text = v_item.item_key
             OR ai.item_code = v_item.item_key)
            AND ai.instrument_id = (
              SELECT instrument_id FROM assessment_instances WHERE id = OLD.id
              );
          END LOOP;
          END IF;
          END IF;

          RETURN NEW;
          END;
        $$
          LANGUAGE plpgsql SECURITY DEFINER;
          """)
    _exec("""
          CREATE TRIGGER assessments_instead_of_update
              INSTEAD OF UPDATE
              ON assessments
              FOR EACH ROW EXECUTE FUNCTION assessments_update_trigger();
          """)

    # INSTEAD OF DELETE trigger
    _exec("""
          CREATE
          OR REPLACE FUNCTION assessments_delete_trigger()
        RETURNS TRIGGER AS $$
          BEGIN
          DELETE
          FROM assessment_instances
          WHERE id = OLD.id;
          RETURN OLD;
          END;
        $$
          LANGUAGE plpgsql SECURITY DEFINER;
          """)
    _exec("""
          CREATE TRIGGER assessments_instead_of_delete
              INSTEAD OF DELETE
              ON assessments
              FOR EACH ROW EXECUTE FUNCTION assessments_delete_trigger();
          """)

    # Grant permissions on the view
    _exec("GRANT SELECT, INSERT, UPDATE, DELETE ON assessments TO authenticated;")
    _exec("GRANT SELECT, INSERT, UPDATE, DELETE ON assessments TO service_role;")

    # -----------------------------------------------------------------------
    # 9b. GRANTS — required after DROP SCHEMA public CASCADE wipes default privs
    # -----------------------------------------------------------------------
    # These are needed because Supabase's initial schema grants are lost when the
    # public schema is recreated. Without them, PostgREST returns 403 even with
    # a valid JWT because the 'authenticated' role has no table-level permission.
    _exec("GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;")
    _exec("GRANT ALL ON ALL TABLES IN SCHEMA public TO authenticated, service_role;")
    _exec("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO authenticated, service_role;")
    _exec("GRANT ALL ON ALL ROUTINES IN SCHEMA public TO authenticated, service_role;")
    # Public-read tables (anon role can SELECT without login)
    for tbl in [
        "extraction_templates_global",
        "extraction_entity_types",
        "extraction_fields",
        "assessment_instruments",
        "assessment_items",
        "ai_assessment_prompts",
    ]:
        _exec(f"GRANT SELECT ON TABLE {tbl} TO anon;")
    # Default privileges so future tables also inherit correct grants
    _exec(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO authenticated, service_role;"
    )
    _exec(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO authenticated, service_role;"
    )
    _exec(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON ROUTINES TO authenticated, service_role;"
    )

    # -----------------------------------------------------------------------
    # 10. SEED DATA — moved to 0002_seed_instruments.py (SRP: schema only here)
    # -----------------------------------------------------------------------

    # ===========================================================================
    # STORAGE POLICIES — must run after application tables (article_files, projects)
    # are created above.  Supabase migration 0014 creates the storage bucket;
    # these policies reference public-schema tables so they live here.
    # ===========================================================================
    # Drop first to make this idempotent (policies may survive public schema wipe
    # because they live on storage.objects, not in the public schema).
    _exec('DROP POLICY IF EXISTS "Members can view article files" ON storage.objects;')
    _exec(
        'DROP POLICY IF EXISTS "Authenticated users can upload article files" ON storage.objects;'
    )
    _exec('DROP POLICY IF EXISTS "Members can update article files" ON storage.objects;')
    _exec('DROP POLICY IF EXISTS "Members can delete article files" ON storage.objects;')
    _exec("""
        CREATE POLICY "Members can view article files"
        ON storage.objects FOR SELECT
        USING (
          bucket_id = 'articles' AND
          EXISTS (
            SELECT 1 FROM public.article_files af
            JOIN public.projects p ON p.id = af.project_id
            WHERE af.storage_key = storage.objects.name
            AND public.is_project_member(p.id, auth.uid())
          )
        );
    """)
    _exec("""
        CREATE POLICY "Authenticated users can upload article files"
        ON storage.objects FOR INSERT
        WITH CHECK (
          bucket_id = 'articles' AND
          auth.uid() IS NOT NULL
        );
    """)
    _exec("""
        CREATE POLICY "Members can update article files"
        ON storage.objects FOR UPDATE
        USING (
          bucket_id = 'articles' AND
          EXISTS (
            SELECT 1 FROM public.article_files af
            JOIN public.projects p ON p.id = af.project_id
            WHERE af.storage_key = storage.objects.name
            AND public.is_project_member(p.id, auth.uid())
          )
        );
    """)
    _exec("""
        CREATE POLICY "Members can delete article files"
        ON storage.objects FOR DELETE
        USING (
          bucket_id = 'articles' AND
          EXISTS (
            SELECT 1 FROM public.article_files af
            JOIN public.projects p ON p.id = af.project_id
            WHERE af.storage_key = storage.objects.name
            AND public.is_project_member(p.id, auth.uid())
          )
        );
    """)


# ===========================================================================
# DOWNGRADE  — drops everything in reverse dependency order
# ===========================================================================


def downgrade() -> None:
    # Drop storage policies created in upgrade (they reference application tables)
    _exec('DROP POLICY IF EXISTS "Members can view article files" ON storage.objects;')
    _exec(
        'DROP POLICY IF EXISTS "Authenticated users can upload article files" ON storage.objects;'
    )
    _exec('DROP POLICY IF EXISTS "Members can update article files" ON storage.objects;')
    _exec('DROP POLICY IF EXISTS "Members can delete article files" ON storage.objects;')

    # Drop view and its triggers/functions first
    _exec("DROP VIEW IF EXISTS assessments CASCADE;")
    _exec("DROP FUNCTION IF EXISTS assessments_insert_trigger() CASCADE;")
    _exec("DROP FUNCTION IF EXISTS assessments_update_trigger() CASCADE;")
    _exec("DROP FUNCTION IF EXISTS assessments_delete_trigger() CASCADE;")

    # Drop helper functions
    for fn in [
        "clone_global_instrument_to_project(uuid,uuid,uuid,text)",
        "get_project_members(uuid)",
        "find_user_id_by_email(text)",
        "create_project_with_member(text,text,review_type,uuid)",
        "get_assessment_instance_children(uuid)",
        "calculate_assessment_instance_progress(uuid)",
        "calculate_model_progress(uuid,uuid)",
        "ensure_single_default_api_key()",
        "validate_instance_project_consistency()",
        "validate_assessment_instance_hierarchy()",
        "validate_extraction_instance_hierarchy()",
        "update_updated_at_column()",
        "set_updated_at()",
        "is_project_manager(uuid,uuid)",
        "is_project_member(uuid,uuid)",
    ]:
        _exec(f"DROP FUNCTION IF EXISTS {fn} CASCADE;")

    # Drop tables in reverse dependency order
    for tbl in [
        "migration_status",
        "user_api_keys",
        "feedback_reports",
        "zotero_integrations",
        "assessment_evidence",
        "assessment_responses",
        "assessment_instances",
        "ai_suggestions",
        "extraction_evidence",
        "extracted_values",
        "ai_assessment_runs",
        "project_assessment_items",
        "project_assessment_instruments",
        "ai_assessments",
        "ai_assessment_prompts",
        "ai_assessment_configs",
        "extraction_runs",
        "extraction_instances",
        "extraction_fields",
        "article_annotations",
        "article_boxes",
        "article_highlights",
        "article_files",
        "assessment_items",
        "assessment_instruments",
        "project_extraction_templates",
        "articles",
        "project_members",
        "projects",
        "extraction_entity_types",
        "extraction_templates_global",
        "profiles",
    ]:
        _exec(f"DROP TABLE IF EXISTS {tbl} CASCADE;")

    # Drop ENUMs
    for typ in [
        "extraction_instance_status",
        "assessment_source",
        "assessment_status",
        "suggestion_status",
        "extraction_run_status",
        "extraction_run_stage",
        "extraction_source",
        "extraction_cardinality",
        "extraction_field_type",
        "extraction_framework",
        "file_role",
        "project_member_role",
        "review_type",
    ]:
        _exec(f"DROP TYPE IF EXISTS {typ} CASCADE;")

    # Drop extensions
    _exec('DROP EXTENSION IF EXISTS "btree_gin";')
    _exec('DROP EXTENSION IF EXISTS "pg_trgm";')
    _exec('DROP EXTENSION IF EXISTS "pgcrypto";')
