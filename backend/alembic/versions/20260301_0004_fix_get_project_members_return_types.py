"""fix get_project_members return type mismatch (varchar vs text)

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-01

PostgreSQL error 42804: RETURNS TABLE declares user_email as text, but
auth.users.email is character varying(255). Cast SELECT columns to text
so the function result type matches.
"""

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
                      u.email::text      AS user_email, p.full_name::text  AS user_full_name, p.avatar_url::text AS user_avatar_url
               FROM project_members pm
                        JOIN auth.users u ON u.id = pm.user_id
                        LEFT JOIN profiles p ON p.id = pm.user_id
               WHERE pm.project_id = p_project_id;
               END;
        $$
               LANGUAGE plpgsql SECURITY DEFINER;
               """)
    op.execute(
        "GRANT EXECUTE ON FUNCTION get_project_members(uuid) TO authenticated, service_role;"
    )


def downgrade() -> None:
    # Restore 0002 version (without ::text casts); may hit 42804 again if downgrading.
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
    op.execute(
        "GRANT EXECUTE ON FUNCTION get_project_members(uuid) TO authenticated, service_role;"
    )
