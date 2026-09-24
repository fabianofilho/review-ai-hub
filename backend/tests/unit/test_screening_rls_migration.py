"""
Tests for the migration that enables RLS on the screening tables (REV-03).

The migration is not applied to a database here; these tests capture the SQL
it emits and check the revision chain.
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_DIR = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    BACKEND_DIR / "alembic" / "versions" / "20260924_008_enable_rls_screening_tables.py"
)
SCREENING_TABLES = [
    "screening_configs",
    "screening_decisions",
    "screening_conflicts",
    "screening_runs",
]


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_20260924_008", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _captured_sql(func_name: str) -> list[str]:
    module = _load_migration()
    fake_op = MagicMock()
    with patch.object(module, "op", fake_op):
        getattr(module, func_name)()
    return [call.args[0] for call in fake_op.execute.call_args_list]


def test_upgrade_enables_rls_on_all_screening_tables():
    statements = _captured_sql("upgrade")
    for table in SCREENING_TABLES:
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in statements


def test_upgrade_creates_member_scoped_select_policy_for_each_table():
    sql = "\n".join(_captured_sql("upgrade"))
    for table in SCREENING_TABLES:
        assert f'CREATE POLICY "{table}_select"' in sql
        assert f"ON public.{table} FOR SELECT TO authenticated" in sql
    assert sql.count("is_project_member(project_id, auth.uid())") >= len(SCREENING_TABLES)
    # No policy may grant unconditional access.
    assert "USING (true)" not in sql
    assert "WITH CHECK (true)" not in sql


def test_decision_writes_are_limited_to_own_reviewer_id():
    sql = "\n".join(_captured_sql("upgrade"))
    insert_policy = sql.split('CREATE POLICY "screening_decisions_insert"')[1].split(
        "CREATE POLICY"
    )[0]
    assert "reviewer_id = auth.uid()" in insert_policy


def test_downgrade_drops_policies_and_disables_rls():
    statements = _captured_sql("downgrade")
    for table in SCREENING_TABLES:
        assert f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY" in statements
        assert any(s.startswith(f'DROP POLICY IF EXISTS "{table}_select"') for s in statements)


def test_migration_follows_screening_tables_on_the_single_head():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()
    assert len(heads) == 1
    revision = script.get_revision("20260924_008")
    assert revision.down_revision == "20260329_007"
    # Later migrations may become the head; this one must stay in its history.
    history = [rev.revision for rev in script.iterate_revisions(heads[0], "base")]
    assert "20260924_008" in history
