"""zotero article parity, sync runs, and author entities

Revision ID: 20260328_006
Revises: 0004
Create Date: 2026-03-28
"""

from alembic import op

revision: str = "20260328_006"
down_revision: str | None = "0004"
branch_labels = None
depends_on = None


def _execute_batch(sql: str) -> None:
    for statement in (chunk.strip() for chunk in sql.split(";")):
        if statement:
            op.execute(statement)


def upgrade() -> None:
    _execute_batch(
        """
        ALTER TABLE public.articles
            ADD COLUMN IF NOT EXISTS sync_state text NOT NULL DEFAULT 'active',
            ADD COLUMN IF NOT EXISTS removed_at_source_at timestamptz NULL,
            ADD COLUMN IF NOT EXISTS last_synced_at timestamptz NULL,
            ADD COLUMN IF NOT EXISTS sync_conflict_log jsonb NULL,
            ADD COLUMN IF NOT EXISTS pdf_extracted_text text NULL,
            ADD COLUMN IF NOT EXISTS semantic_abstract_text text NULL,
            ADD COLUMN IF NOT EXISTS semantic_fulltext_text text NULL,
            ADD COLUMN IF NOT EXISTS source_lineage text NULL;

        CREATE INDEX IF NOT EXISTS idx_articles_sync_state
            ON public.articles(sync_state);
        CREATE INDEX IF NOT EXISTS idx_articles_last_synced_at
            ON public.articles(last_synced_at DESC);

        CREATE TABLE IF NOT EXISTS public.article_authors
        (
            id
            uuid
            PRIMARY
            KEY
            DEFAULT
            gen_random_uuid
        (
        ),
            normalized_name text NOT NULL,
            display_name text NOT NULL,
            orcid text NULL,
            source_hint jsonb NULL,
            created_at timestamptz NOT NULL DEFAULT now
        (
        ),
            updated_at timestamptz NOT NULL DEFAULT now
        (
        )
            );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_article_authors_normalized_orcid
            ON public.article_authors(normalized_name, COALESCE (orcid, ''));
        CREATE INDEX IF NOT EXISTS idx_article_authors_normalized_name
            ON public.article_authors(normalized_name);

        CREATE TABLE IF NOT EXISTS public.article_author_links
        (
            id
            uuid
            PRIMARY
            KEY
            DEFAULT
            gen_random_uuid
        (
        ),
            article_id uuid NOT NULL REFERENCES public.articles
        (
            id
        ) ON DELETE CASCADE,
            author_id uuid NOT NULL REFERENCES public.article_authors
        (
            id
        )
          ON DELETE RESTRICT,
            author_order integer NOT NULL,
            creator_type text NOT NULL DEFAULT 'author',
            raw_creator_payload jsonb NULL,
            created_at timestamptz NOT NULL DEFAULT now
        (
        ),
            updated_at timestamptz NOT NULL DEFAULT now
        (
        ),
            CONSTRAINT article_author_links_article_id_author_order_key UNIQUE
        (
            article_id,
            author_order
        ),
            CONSTRAINT article_author_links_article_id_author_id_creator_type_key UNIQUE
        (
            article_id,
            author_id,
            creator_type
        )
            );

        CREATE INDEX IF NOT EXISTS idx_article_author_links_article_id
            ON public.article_author_links(article_id);
        CREATE INDEX IF NOT EXISTS idx_article_author_links_author_id
            ON public.article_author_links(author_id);

        CREATE TABLE IF NOT EXISTS public.article_sync_runs
        (
            id
            uuid
            PRIMARY
            KEY
            DEFAULT
            gen_random_uuid
        (
        ),
            project_id uuid NOT NULL REFERENCES public.projects
        (
            id
        ) ON DELETE CASCADE,
            requested_by_user_id uuid NOT NULL,
            started_at timestamptz NOT NULL DEFAULT now
        (
        ),
            completed_at timestamptz NULL,
            status text NOT NULL DEFAULT 'pending',
            source text NOT NULL DEFAULT 'zotero',
            source_collection_key text NULL,
            total_received integer NOT NULL DEFAULT 0,
            persisted integer NOT NULL DEFAULT 0,
            updated integer NOT NULL DEFAULT 0,
            skipped integer NOT NULL DEFAULT 0,
            failed integer NOT NULL DEFAULT 0,
            removed_at_source integer NOT NULL DEFAULT 0,
            reactivated integer NOT NULL DEFAULT 0,
            failure_summary jsonb NULL,
            created_at timestamptz NOT NULL DEFAULT now
        (
        ),
            updated_at timestamptz NOT NULL DEFAULT now
        (
        )
            );

        CREATE INDEX IF NOT EXISTS idx_article_sync_runs_project_id
            ON public.article_sync_runs(project_id);
        CREATE INDEX IF NOT EXISTS idx_article_sync_runs_requested_by_user_id
            ON public.article_sync_runs(requested_by_user_id);
        CREATE INDEX IF NOT EXISTS idx_article_sync_runs_status
            ON public.article_sync_runs(status);

        CREATE TABLE IF NOT EXISTS public.article_sync_events
        (
            id
            uuid
            PRIMARY
            KEY
            DEFAULT
            gen_random_uuid
        (
        ),
            project_id uuid NOT NULL REFERENCES public.projects
        (
            id
        ) ON DELETE CASCADE,
            article_id uuid NULL REFERENCES public.articles
        (
            id
        )
          ON DELETE SET NULL,
            sync_run_id uuid NOT NULL REFERENCES public.article_sync_runs
        (
            id
        )
          ON DELETE CASCADE,
            zotero_item_key text NULL,
            status text NOT NULL,
            authority_rule_applied text NULL,
            error_code text NULL,
            error_message text NULL,
            event_payload jsonb NULL,
            processed_at timestamptz NOT NULL DEFAULT now
        (
        ),
            created_at timestamptz NOT NULL DEFAULT now
        (
        ),
            updated_at timestamptz NOT NULL DEFAULT now
        (
        )
            );

        CREATE INDEX IF NOT EXISTS idx_article_sync_events_sync_run_id
            ON public.article_sync_events(sync_run_id);
        CREATE INDEX IF NOT EXISTS idx_article_sync_events_project_id
            ON public.article_sync_events(project_id);
        CREATE INDEX IF NOT EXISTS idx_article_sync_events_status
            ON public.article_sync_events(status);
        """
    )

    # RLS + policies for new tables.
    _execute_batch(
        """
        ALTER TABLE public.article_authors ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.article_author_links ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.article_sync_runs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.article_sync_events ENABLE ROW LEVEL SECURITY;

        CREATE
        POLICY "article_authors_select"
            ON public.article_authors FOR
        SELECT TO authenticated
            USING (
            EXISTS (
            SELECT 1
            FROM public.article_author_links aal
            JOIN public.articles a ON a.id = aal.article_id
            JOIN public.project_members pm ON pm.project_id = a.project_id
            WHERE aal.author_id = article_authors.id
            AND pm.user_id = auth.uid()
            )
            );
        CREATE
        POLICY "article_authors_manage"
            ON public.article_authors FOR ALL TO authenticated
            USING (true)
            WITH CHECK (true);

        CREATE
        POLICY "article_author_links_select"
            ON public.article_author_links FOR
        SELECT TO authenticated
            USING (
            EXISTS (
            SELECT 1
            FROM public.articles a
            JOIN public.project_members pm ON pm.project_id = a.project_id
            WHERE a.id = article_author_links.article_id
            AND pm.user_id = auth.uid()
            )
            );
        CREATE
        POLICY "article_author_links_insert"
            ON public.article_author_links FOR INSERT TO authenticated
            WITH CHECK (
                EXISTS (
                    SELECT 1
                    FROM public.articles a
                    JOIN public.project_members pm ON pm.project_id = a.project_id
                    WHERE a.id = article_author_links.article_id
                      AND pm.user_id = auth.uid()
                )
            );
        CREATE
        POLICY "article_author_links_update"
            ON public.article_author_links FOR
        UPDATE TO authenticated
            USING (
            EXISTS (
            SELECT 1
            FROM public.articles a
            JOIN public.project_members pm ON pm.project_id = a.project_id
            WHERE a.id = article_author_links.article_id
            AND pm.user_id = auth.uid()
            )
            )
        WITH CHECK (
            EXISTS (
            SELECT 1
            FROM public.articles a
            JOIN public.project_members pm ON pm.project_id = a.project_id
            WHERE a.id = article_author_links.article_id
            AND pm.user_id = auth.uid()
            )
            );
        CREATE
        POLICY "article_author_links_delete"
            ON public.article_author_links FOR DELETE
        TO authenticated
            USING (
                EXISTS (
                    SELECT 1
                    FROM public.articles a
                    JOIN public.project_members pm ON pm.project_id = a.project_id
                    WHERE a.id = article_author_links.article_id
                      AND pm.user_id = auth.uid()
                )
            );

        CREATE
        POLICY "article_sync_runs_select"
            ON public.article_sync_runs FOR
        SELECT TO authenticated
            USING (
            EXISTS (
            SELECT 1
            FROM public.project_members pm
            WHERE pm.project_id = article_sync_runs.project_id
            AND pm.user_id = auth.uid()
            )
            );
        CREATE
        POLICY "article_sync_runs_insert"
            ON public.article_sync_runs FOR INSERT TO authenticated
            WITH CHECK (
                EXISTS (
                    SELECT 1
                    FROM public.project_members pm
                    WHERE pm.project_id = article_sync_runs.project_id
                      AND pm.user_id = auth.uid()
                )
            );
        CREATE
        POLICY "article_sync_runs_update"
            ON public.article_sync_runs FOR
        UPDATE TO authenticated
            USING (
            EXISTS (
            SELECT 1
            FROM public.project_members pm
            WHERE pm.project_id = article_sync_runs.project_id
            AND pm.user_id = auth.uid()
            )
            )
        WITH CHECK (
            EXISTS (
            SELECT 1
            FROM public.project_members pm
            WHERE pm.project_id = article_sync_runs.project_id
            AND pm.user_id = auth.uid()
            )
            );
        CREATE
        POLICY "article_sync_runs_delete"
            ON public.article_sync_runs FOR DELETE
        TO authenticated
            USING (
                EXISTS (
                    SELECT 1
                    FROM public.project_members pm
                    WHERE pm.project_id = article_sync_runs.project_id
                      AND pm.user_id = auth.uid()
                )
            );

        CREATE
        POLICY "article_sync_events_select"
            ON public.article_sync_events FOR
        SELECT TO authenticated
            USING (
            EXISTS (
            SELECT 1
            FROM public.project_members pm
            WHERE pm.project_id = article_sync_events.project_id
            AND pm.user_id = auth.uid()
            )
            );
        CREATE
        POLICY "article_sync_events_insert"
            ON public.article_sync_events FOR INSERT TO authenticated
            WITH CHECK (
                EXISTS (
                    SELECT 1
                    FROM public.project_members pm
                    WHERE pm.project_id = article_sync_events.project_id
                      AND pm.user_id = auth.uid()
                )
            );
        CREATE
        POLICY "article_sync_events_update"
            ON public.article_sync_events FOR
        UPDATE TO authenticated
            USING (
            EXISTS (
            SELECT 1
            FROM public.project_members pm
            WHERE pm.project_id = article_sync_events.project_id
            AND pm.user_id = auth.uid()
            )
            )
        WITH CHECK (
            EXISTS (
            SELECT 1
            FROM public.project_members pm
            WHERE pm.project_id = article_sync_events.project_id
            AND pm.user_id = auth.uid()
            )
            );
        CREATE
        POLICY "article_sync_events_delete"
            ON public.article_sync_events FOR DELETE
        TO authenticated
            USING (
                EXISTS (
                    SELECT 1
                    FROM public.project_members pm
                    WHERE pm.project_id = article_sync_events.project_id
                      AND pm.user_id = auth.uid()
                )
            );
        """
    )


def downgrade() -> None:
    _execute_batch(
        """
        DROP POLICY IF EXISTS "article_sync_events_delete" ON public.article_sync_events;
        DROP POLICY IF EXISTS "article_sync_events_update" ON public.article_sync_events;
        DROP POLICY IF EXISTS "article_sync_events_insert" ON public.article_sync_events;
        DROP POLICY IF EXISTS "article_sync_events_select" ON public.article_sync_events;
        DROP POLICY IF EXISTS "article_sync_runs_delete" ON public.article_sync_runs;
        DROP POLICY IF EXISTS "article_sync_runs_update" ON public.article_sync_runs;
        DROP POLICY IF EXISTS "article_sync_runs_insert" ON public.article_sync_runs;
        DROP POLICY IF EXISTS "article_sync_runs_select" ON public.article_sync_runs;
        DROP POLICY IF EXISTS "article_author_links_delete" ON public.article_author_links;
        DROP POLICY IF EXISTS "article_author_links_update" ON public.article_author_links;
        DROP POLICY IF EXISTS "article_author_links_insert" ON public.article_author_links;
        DROP POLICY IF EXISTS "article_author_links_select" ON public.article_author_links;
        DROP POLICY IF EXISTS "article_authors_manage" ON public.article_authors;
        DROP POLICY IF EXISTS "article_authors_select" ON public.article_authors;

        DROP TABLE IF EXISTS public.article_sync_events;
        DROP TABLE IF EXISTS public.article_sync_runs;
        DROP TABLE IF EXISTS public.article_author_links;
        DROP TABLE IF EXISTS public.article_authors;

        DROP INDEX IF EXISTS public.idx_articles_last_synced_at;
        DROP INDEX IF EXISTS public.idx_articles_sync_state;

        ALTER TABLE public.articles
            DROP COLUMN IF EXISTS source_lineage,
            DROP COLUMN IF EXISTS semantic_fulltext_text,
            DROP COLUMN IF EXISTS semantic_abstract_text,
            DROP COLUMN IF EXISTS pdf_extracted_text,
            DROP COLUMN IF EXISTS sync_conflict_log,
            DROP COLUMN IF EXISTS last_synced_at,
            DROP COLUMN IF EXISTS removed_at_source_at,
            DROP COLUMN IF EXISTS sync_state;
        """
    )
