"""restore chk_extraction_instance_scope on assessment_instances

Revision ID: 20260924_008
Revises: 20260329_007
Create Date: 2026-09-24

Supabase migration 0030_assessment_restructure created the check constraint
chk_extraction_instance_scope, which only allows extraction_instance_id on root
assessment instances (PROBAST per model is attached to the root instance, never
to a child). No later migration dropped it, but it was left out when the
Supabase migrations were consolidated into revision 0001, so databases built
from Alembic alone do not enforce the invariant.

Databases that were created by the Supabase migrations and then stamped at
0001 already have the constraint, so it is only added when missing.
"""

from alembic import op

revision: str = "20260924_008"
down_revision: str | None = "20260329_007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'chk_extraction_instance_scope'
                  AND conrelid = 'public.assessment_instances'::regclass
            ) THEN
                ALTER TABLE public.assessment_instances
                    ADD CONSTRAINT chk_extraction_instance_scope CHECK (
                        extraction_instance_id IS NULL OR parent_instance_id IS NULL
                    );
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.assessment_instances "
        "DROP CONSTRAINT IF EXISTS chk_extraction_instance_scope;"
    )
