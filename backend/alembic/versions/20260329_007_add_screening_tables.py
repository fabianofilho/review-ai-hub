"""add screening workflow tables

Revision ID: 20260329_007
Revises: 20260328_006
Create Date: 2026-03-29
"""

from alembic import op

revision: str = "20260329_007"
down_revision: str | None = "20260328_006"
branch_labels = None
depends_on = None


def _execute_batch(sql: str) -> None:
    for statement in (chunk.strip() for chunk in sql.split(";")):
        if statement:
            op.execute(statement)


def upgrade() -> None:
    _execute_batch("""
        CREATE TABLE IF NOT EXISTS public.screening_configs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
            phase screening_phase NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            require_dual_review BOOLEAN NOT NULL DEFAULT false,
            blind_mode BOOLEAN NOT NULL DEFAULT false,
            criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
            ai_model_name VARCHAR(100) DEFAULT 'gpt-4o-mini',
            ai_system_instruction TEXT,
            created_by UUID NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_screening_configs_project_phase UNIQUE (project_id, phase)
        );

        CREATE INDEX IF NOT EXISTS idx_screening_configs_project_id ON public.screening_configs(project_id);
        CREATE INDEX IF NOT EXISTS idx_screening_configs_criteria_gin ON public.screening_configs USING gin(criteria);

        CREATE TABLE IF NOT EXISTS public.screening_decisions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
            article_id UUID NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
            reviewer_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
            phase screening_phase NOT NULL,
            decision screening_decision NOT NULL,
            reason TEXT,
            criteria_responses JSONB NOT NULL DEFAULT '{}'::jsonb,
            is_ai_assisted BOOLEAN NOT NULL DEFAULT false,
            ai_suggestion_id UUID REFERENCES public.ai_suggestions(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_screening_decisions_article_reviewer_phase
                UNIQUE (project_id, article_id, reviewer_id, phase)
        );

        CREATE INDEX IF NOT EXISTS idx_screening_decisions_project_id ON public.screening_decisions(project_id);
        CREATE INDEX IF NOT EXISTS idx_screening_decisions_article_id ON public.screening_decisions(article_id);
        CREATE INDEX IF NOT EXISTS idx_screening_decisions_reviewer_id ON public.screening_decisions(reviewer_id);
        CREATE INDEX IF NOT EXISTS idx_screening_decisions_criteria_gin ON public.screening_decisions USING gin(criteria_responses);

        CREATE TABLE IF NOT EXISTS public.screening_conflicts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
            article_id UUID NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE,
            phase screening_phase NOT NULL,
            decision_1_id UUID NOT NULL REFERENCES public.screening_decisions(id) ON DELETE CASCADE,
            decision_2_id UUID NOT NULL REFERENCES public.screening_decisions(id) ON DELETE CASCADE,
            status screening_conflict_status NOT NULL DEFAULT 'conflict',
            resolved_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
            resolved_decision screening_decision,
            resolved_reason TEXT,
            resolved_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_screening_conflicts_article_phase
                UNIQUE (project_id, article_id, phase)
        );

        CREATE INDEX IF NOT EXISTS idx_screening_conflicts_project_id ON public.screening_conflicts(project_id);
        CREATE INDEX IF NOT EXISTS idx_screening_conflicts_article_id ON public.screening_conflicts(article_id);

        CREATE TABLE IF NOT EXISTS public.screening_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
            phase screening_phase NOT NULL,
            stage VARCHAR(50) NOT NULL,
            status extraction_run_status NOT NULL DEFAULT 'pending',
            parameters JSONB NOT NULL DEFAULT '{}'::jsonb,
            results JSONB NOT NULL DEFAULT '{}'::jsonb,
            error_message TEXT,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_by UUID NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE INDEX IF NOT EXISTS idx_screening_runs_project_id ON public.screening_runs(project_id);
        CREATE INDEX IF NOT EXISTS idx_screening_runs_status ON public.screening_runs(status);
        CREATE INDEX IF NOT EXISTS idx_screening_runs_parameters_gin ON public.screening_runs USING gin(parameters);
        CREATE INDEX IF NOT EXISTS idx_screening_runs_results_gin ON public.screening_runs USING gin(results);

        ALTER TABLE public.articles
            ADD COLUMN IF NOT EXISTS screening_phase VARCHAR(50);

        ALTER TABLE public.ai_suggestions
            ADD COLUMN IF NOT EXISTS screening_run_id UUID
                REFERENCES public.screening_runs(id) ON DELETE CASCADE;

        CREATE INDEX IF NOT EXISTS idx_ai_suggestions_screening_run_id
            ON public.ai_suggestions(screening_run_id)
            WHERE screening_run_id IS NOT NULL
    """)


def downgrade() -> None:
    _execute_batch("""
        DROP INDEX IF EXISTS public.idx_ai_suggestions_screening_run_id;
        ALTER TABLE public.ai_suggestions DROP COLUMN IF EXISTS screening_run_id;
        ALTER TABLE public.articles DROP COLUMN IF EXISTS screening_phase;
        DROP TABLE IF EXISTS public.screening_runs;
        DROP TABLE IF EXISTS public.screening_conflicts;
        DROP TABLE IF EXISTS public.screening_decisions;
        DROP TABLE IF EXISTS public.screening_configs
    """)
