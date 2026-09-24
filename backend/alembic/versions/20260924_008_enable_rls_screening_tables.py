"""enable row level security on screening tables

Revision ID: 20260924_008
Revises: 20260329_007
Create Date: 2026-09-24

The screening tables created in 20260329_007 were left without RLS. Because
0001_initial_public_schema grants ALL on future public tables to the
`authenticated` role, any logged-in user could read and modify screening data
of every project through PostgREST. This migration enables RLS and restricts
access to project members, following the policies used for the other
project-scoped tables (is_project_member / is_project_manager).
"""

from alembic import op

revision: str = "20260924_008"
down_revision: str | None = "20260329_007"
branch_labels = None
depends_on = None


SCREENING_TABLES = (
    "screening_configs",
    "screening_decisions",
    "screening_conflicts",
    "screening_runs",
)


def _execute_batch(sql: str) -> None:
    for statement in (chunk.strip() for chunk in sql.split(";")):
        if statement:
            op.execute(statement)


def upgrade() -> None:
    for table in SCREENING_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")

    _execute_batch(
        """
        CREATE POLICY "screening_configs_select"
            ON public.screening_configs FOR SELECT TO authenticated
            USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "screening_configs_insert"
            ON public.screening_configs FOR INSERT TO authenticated
            WITH CHECK (is_project_member(project_id, auth.uid()));
        CREATE POLICY "screening_configs_update"
            ON public.screening_configs FOR UPDATE TO authenticated
            USING (is_project_member(project_id, auth.uid()))
            WITH CHECK (is_project_member(project_id, auth.uid()));
        CREATE POLICY "screening_configs_delete"
            ON public.screening_configs FOR DELETE TO authenticated
            USING (is_project_manager(project_id, auth.uid()));

        CREATE POLICY "screening_decisions_select"
            ON public.screening_decisions FOR SELECT TO authenticated
            USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "screening_decisions_insert"
            ON public.screening_decisions FOR INSERT TO authenticated
            WITH CHECK (
                is_project_member(project_id, auth.uid())
                AND reviewer_id = auth.uid()
            );
        CREATE POLICY "screening_decisions_update"
            ON public.screening_decisions FOR UPDATE TO authenticated
            USING (
                is_project_member(project_id, auth.uid())
                AND reviewer_id = auth.uid()
            )
            WITH CHECK (
                is_project_member(project_id, auth.uid())
                AND reviewer_id = auth.uid()
            );
        CREATE POLICY "screening_decisions_delete"
            ON public.screening_decisions FOR DELETE TO authenticated
            USING (
                is_project_manager(project_id, auth.uid())
                OR (
                    is_project_member(project_id, auth.uid())
                    AND reviewer_id = auth.uid()
                )
            );

        CREATE POLICY "screening_conflicts_select"
            ON public.screening_conflicts FOR SELECT TO authenticated
            USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "screening_conflicts_insert"
            ON public.screening_conflicts FOR INSERT TO authenticated
            WITH CHECK (is_project_member(project_id, auth.uid()));
        CREATE POLICY "screening_conflicts_update"
            ON public.screening_conflicts FOR UPDATE TO authenticated
            USING (is_project_member(project_id, auth.uid()))
            WITH CHECK (is_project_member(project_id, auth.uid()));
        CREATE POLICY "screening_conflicts_delete"
            ON public.screening_conflicts FOR DELETE TO authenticated
            USING (is_project_manager(project_id, auth.uid()));

        CREATE POLICY "screening_runs_select"
            ON public.screening_runs FOR SELECT TO authenticated
            USING (is_project_member(project_id, auth.uid()));
        CREATE POLICY "screening_runs_insert"
            ON public.screening_runs FOR INSERT TO authenticated
            WITH CHECK (is_project_member(project_id, auth.uid()));
        CREATE POLICY "screening_runs_update"
            ON public.screening_runs FOR UPDATE TO authenticated
            USING (is_project_member(project_id, auth.uid()))
            WITH CHECK (is_project_member(project_id, auth.uid()))
        """
    )


def downgrade() -> None:
    _execute_batch(
        """
        DROP POLICY IF EXISTS "screening_runs_update" ON public.screening_runs;
        DROP POLICY IF EXISTS "screening_runs_insert" ON public.screening_runs;
        DROP POLICY IF EXISTS "screening_runs_select" ON public.screening_runs;
        DROP POLICY IF EXISTS "screening_conflicts_delete" ON public.screening_conflicts;
        DROP POLICY IF EXISTS "screening_conflicts_update" ON public.screening_conflicts;
        DROP POLICY IF EXISTS "screening_conflicts_insert" ON public.screening_conflicts;
        DROP POLICY IF EXISTS "screening_conflicts_select" ON public.screening_conflicts;
        DROP POLICY IF EXISTS "screening_decisions_delete" ON public.screening_decisions;
        DROP POLICY IF EXISTS "screening_decisions_update" ON public.screening_decisions;
        DROP POLICY IF EXISTS "screening_decisions_insert" ON public.screening_decisions;
        DROP POLICY IF EXISTS "screening_decisions_select" ON public.screening_decisions;
        DROP POLICY IF EXISTS "screening_configs_delete" ON public.screening_configs;
        DROP POLICY IF EXISTS "screening_configs_update" ON public.screening_configs;
        DROP POLICY IF EXISTS "screening_configs_insert" ON public.screening_configs;
        DROP POLICY IF EXISTS "screening_configs_select" ON public.screening_configs
        """
    )
    for table in SCREENING_TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
