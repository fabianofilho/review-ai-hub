"""fix get_project_members column names and missing fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-01

The original function (consolidated in 0001) returned wrong column aliases:
  email, full_name, avatar_url, joined_at
but the frontend and generated Supabase types expect:
  user_email, user_full_name, user_avatar_url, created_at

It also omitted the `id` (project_members.id) and `permissions` columns,
which the frontend needs for update/delete operations.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DROP required because PostgreSQL won't allow OR REPLACE when the
    # RETURNS TABLE signature changes (different column names / count).
    op.execute("DROP FUNCTION IF EXISTS get_project_members(uuid);")
    op.execute("""
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
    # Re-grant after DROP+CREATE (GRANT ALL ON ALL ROUTINES only covers
    # functions that existed at grant time; the new function needs it explicitly)
    op.execute(
        "GRANT EXECUTE ON FUNCTION get_project_members(uuid) TO authenticated, service_role;"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS get_project_members(uuid);")
    # Restore the original (broken) signature so rollback is clean
    op.execute("""
               CREATE
               OR REPLACE FUNCTION get_project_members(p_project_id uuid)
        RETURNS TABLE (
            user_id    uuid,
            email      text,
            full_name  text,
            avatar_url text,
            role       project_member_role,
            joined_at  timestamptz
        ) AS $$
               BEGIN
               RETURN QUERY
               SELECT pm.user_id,
                      u.email,
                      p.full_name,
                      p.avatar_url,
                      pm.role,
                      pm.created_at AS joined_at
               FROM project_members pm
                        JOIN auth.users u ON u.id = pm.user_id
                        LEFT JOIN profiles p ON p.id = pm.user_id
               WHERE pm.project_id = p_project_id;
               END;
        $$
               LANGUAGE plpgsql SECURITY DEFINER;
               """)
