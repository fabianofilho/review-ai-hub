"""
Alembic Environment Configuration.

Configures Alembic to:
- Use the async SQLAlchemy engine (asyncpg) via a sync bridge
- Restrict autogenerate to the `public` schema only
- Exclude Supabase-injected tables from drift detection
- Override the database URL from app settings at runtime
- Suppress schema-noise from legacy constraint/index naming
"""

import asyncio
import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import app settings and Base — sys.path is extended by `prepend_sys_path = .` in alembic.ini
from app.core.config import settings
from app.models import Base  # noqa: F401  — side-effect: registers all models in metadata

# ---------------------------------------------------------------------------
# Alembic config object (wraps alembic.ini)
# ---------------------------------------------------------------------------
config = context.config

# Note: fileConfig() is intentionally not called here because the application
# uses structlog for logging. Mixing fileConfig() with structlog causes the
# alembic.ini format template to be emitted literally to stderr.

logger = logging.getLogger("alembic.env")


# ---------------------------------------------------------------------------
# Override database URL from app settings (never use the placeholder in .ini)
# ---------------------------------------------------------------------------
# Migrations must use the direct Supabase connection (port 5432), NOT the
# PgBouncer pooler (port 6543, transaction mode), which is incompatible with
# DDL and asyncpg prepared statements.
#
# DIRECT_DATABASE_URL should be set in production (e.g. Render env vars) to
# the Supabase direct connection string. Falls back to DATABASE_URL for local
# dev where there is no pooler.
def _to_asyncpg_url(database_url: str) -> str:
    async_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    parsed = urlparse(async_url)
    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "sslmode" in query_items and "ssl" not in query_items:
        query_items["ssl"] = query_items.pop("sslmode")
    return urlunparse(parsed._replace(query=urlencode(query_items)))


_direct_url = settings.DIRECT_DATABASE_URL or str(settings.DATABASE_URL)
_migration_url = _to_asyncpg_url(_direct_url)
config.set_main_option("sqlalchemy.url", _migration_url)

# ---------------------------------------------------------------------------
# Model metadata — Alembic compares this against the live DB for autogenerate
# ---------------------------------------------------------------------------
target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Tables injected by Supabase that Alembic must never manage
# ---------------------------------------------------------------------------
_SUPABASE_INJECTED_TABLES: frozenset[str] = frozenset(
    {
        "spatial_ref_sys",
        "geography_columns",
        "geometry_columns",
        "raster_columns",
        "raster_overviews",
        # migration_status was created by a Supabase migration (0032) for one-time
        # bookkeeping; it has no SQLAlchemy model, so exclude it from drift detection.
        "migration_status",
    }
)

# ---------------------------------------------------------------------------
# FK constraints that exist in the DB but intentionally have no SQLAlchemy
# model counterpart (e.g., cross-schema FKs to auth.* tables).
# ---------------------------------------------------------------------------
_SQL_ONLY_CONSTRAINTS: frozenset[str] = frozenset(
    {
        # profiles.id → auth.users(id): cross-schema FK excluded from models
        # per research.md §2 (managing auth.* references only in raw SQL).
        "profiles_id_fkey",
    }
)


def include_object(
    object: object,  # noqa: A002
    name: str | None,
    type_: str,
    reflected: bool,  # noqa: FBT001
    compare_to: object,
) -> bool:
    """
    Restrict Alembic autogenerate to the public schema only.

    Excludes:
    - Any table that lives outside the `public` schema (auth.*, storage.*)
    - Known Supabase-injected tables in `public` (extensions, PostGIS views)
    - Tables that exist in the DB but have no SQLAlchemy model counterpart
      (SQL-only tables managed via raw SQL in migration files)
    - Unique/FK constraints in the DB that have no model counterpart
      (SQL-only constraints defined only via op.execute())
    - Indexes reflected from the DB that have no model-side counterpart
      (prevents spurious DROP INDEX for legacy-named indexes)
    - Model-only indexes whose names follow the ix_public_* convention
      (generated from index=True on columns that already have legacy DB indexes)
    """
    if type_ == "table":
        schema = getattr(object, "schema", None)
        if schema is not None and schema != "public":
            return False
        if name in _SUPABASE_INJECTED_TABLES:
            return False
        # Exclude tables that are in the DB but have no corresponding SQLAlchemy model.
        # These are "SQL-only" tables (e.g., article_annotations, feedback_reports)
        # whose lifecycle is managed via op.execute() in migration files.
        if reflected and compare_to is None:
            return False

    elif type_ in ("unique_constraint", "foreign_key_constraint"):
        # Exclude constraints that exist in the DB but have no model counterpart.
        # These are SQL-only constraints defined via op.execute() in migrations.
        if reflected and compare_to is None:
            return False
        # Exclude known cross-schema constraints (e.g., profiles → auth.users).
        if name in _SQL_ONLY_CONSTRAINTS:
            return False

    elif type_ == "index":
        # Exclude indexes reflected from the DB that have no model-side counterpart.
        # This prevents spurious DROP INDEX for legacy-named indexes (e.g., idx_xxx)
        # that exist in the DB but don't match model-generated convention names.
        if reflected and compare_to is None:
            return False
        # Exclude model-only indexes with convention names (ix_public_*) when they
        # have no DB counterpart — these arise from index=True on columns that already
        # have legacy-named DB indexes.  Prevents spurious CREATE INDEX duplication.
        if not reflected and compare_to is None and name and name.startswith("ix_public_"):
            return False

    return True


# ---------------------------------------------------------------------------
# process_revision_directives: suppress schema-noise from autogenerate
# ---------------------------------------------------------------------------
def _suppress_autogenerate_noise(
    context: Any,  # noqa: ARG001
    revision: Any,  # noqa: ARG001
    directives: list[Any],
) -> None:
    """Remove spurious no-op changes from autogenerate output.

    Handles two classes of noise that arise from the initial migration using
    raw op.execute() SQL instead of Alembic ORM operations:

    1. FK drop+create pairs with the *same* name: these are caused by
       SQLAlchemy models using ``ForeignKey("public.table.id")`` (explicit
       referent_schema) while the DB FK was created without schema prefix.
       Alembic sees a ``referent_schema`` mismatch and generates DROP+CREATE
       even though the FK is semantically identical.  Since the names are
       identical, we drop both ops.

    2. Table-comment removal (DropTableCommentOp): the initial migration SQL
       includes ``COMMENT ON TABLE ...`` statements, but SQLAlchemy models
       don't define table comments.  Suppress the spurious removal.

    3. Column-comment removal (AlterColumnOp where only the comment changes):
       same rationale as table comments — SQL-defined comments have no model
       counterpart so Alembic generates ``comment=None`` alterations.

    Note: Autogenerate nests per-table ops inside ``ModifyTableOps`` containers.
    This function descends into those containers to apply filtering.
    """
    # Lazy-import Alembic ops to avoid circular import at module load time.
    try:
        from alembic.operations import ops as alembic_ops
    except ImportError:
        return

    if not directives:
        return

    script = directives[0]
    if not hasattr(script, "upgrade_ops") or script.upgrade_ops is None:
        return

    top_level_ops: list[Any] = script.upgrade_ops.ops

    # ---- Flatten for FK collection (ops may be nested in ModifyTableOps) ----
    def _leaf_ops(op_list: list[Any]):
        """Yield leaf-level ops, descending into ModifyTableOps containers."""
        for op in op_list:
            if isinstance(op, alembic_ops.ModifyTableOps):
                yield from op.ops
            else:
                yield op

    # ---- Pass 1: collect FK constraint names that appear in BOTH drop and create ----
    # Keys: (table_name, constraint_name_str)
    dropped_fk: set[tuple[str, str]] = set()
    created_fk: set[tuple[str, str]] = set()

    for op in _leaf_ops(top_level_ops):
        if isinstance(op, alembic_ops.DropConstraintOp):
            # Use getattr to avoid Pyright errors on dynamically-set attribute.
            op_type = getattr(op, "type_", None) or getattr(op, "constraint_type", None)
            if op_type == "foreignkey":
                cname = str(op.constraint_name) if op.constraint_name else ""
                dropped_fk.add((op.table_name, cname))
        elif isinstance(op, alembic_ops.CreateForeignKeyOp):
            cname = str(op.constraint_name) if op.constraint_name else ""
            created_fk.add((op.source_table, cname))

    # Keys present in both = same-name drop+create → functionally a no-op.
    fk_noop_keys: frozenset[tuple[str, str]] = frozenset(dropped_fk) & frozenset(created_fk)

    # ---- Pass 2: predicate — return False for ops that should be suppressed ----
    def _is_comment_only_alter(op: Any) -> bool:
        """Return True if the AlterColumnOp changes only the column comment."""
        if not isinstance(op, alembic_ops.AlterColumnOp):
            return False
        # If any structural field is being modified, this is NOT comment-only.
        if getattr(op, "modify_type", None) is not None:
            return False
        if getattr(op, "modify_nullable", None) is not None:
            return False
        if getattr(op, "modify_server_default", False):
            return False
        # Only modify_comment (and existing_* fields) should be non-None/False.
        return getattr(op, "modify_name", None) is None

    def _keep(op: Any) -> bool:
        """Return False for noise ops that should be suppressed."""
        # Remove same-name FK drop+create pairs (referent_schema normalization no-ops).
        if isinstance(op, alembic_ops.DropConstraintOp):
            op_type = getattr(op, "type_", None) or getattr(op, "constraint_type", None)
            if op_type == "foreignkey":
                cname = str(op.constraint_name) if op.constraint_name else ""
                if (op.table_name, cname) in fk_noop_keys:
                    return False

        if isinstance(op, alembic_ops.CreateForeignKeyOp):
            cname = str(op.constraint_name) if op.constraint_name else ""
            if (op.source_table, cname) in fk_noop_keys:
                return False

        # Remove table-comment removal ops (SQL-defined COMMENT ON TABLE).
        if isinstance(op, alembic_ops.DropTableCommentOp):
            return False

        # Remove column-comment-only AlterColumnOp.
        return not _is_comment_only_alter(op)

    # ---- Pass 3: filter, handling ModifyTableOps nesting ----
    total_before = 0
    total_after = 0
    filtered_top: list[Any] = []

    for op in top_level_ops:
        if isinstance(op, alembic_ops.ModifyTableOps):
            before = len(op.ops)
            op.ops = [sub_op for sub_op in op.ops if _keep(sub_op)]
            after = len(op.ops)
            total_before += before
            total_after += after
            if op.ops:  # keep only non-empty ModifyTableOps containers
                filtered_top.append(op)
        else:
            total_before += 1
            if _keep(op):
                total_after += 1
                filtered_top.append(op)

    script.upgrade_ops.ops = filtered_top

    suppressed_count = total_before - total_after
    if suppressed_count > 0:
        logger.info(
            "Suppressed %d autogenerate noise operations (%d FK no-op pairs).",
            suppressed_count,
            len(fk_noop_keys),
        )


# ---------------------------------------------------------------------------
# Core migration runner (sync — called via connection.run_sync)
# ---------------------------------------------------------------------------
def _do_run_migrations(connection: object) -> None:
    context.configure(
        connection=connection,  # type: ignore[arg-type]
        target_metadata=target_metadata,
        include_object=include_object,
        compare_type=True,
        include_schemas=False,
        process_revision_directives=_suppress_autogenerate_noise,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Offline mode — generates SQL script without a live DB connection
# ---------------------------------------------------------------------------
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script output, no live DB)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
        process_revision_directives=_suppress_autogenerate_noise,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode — async engine + sync bridge
# ---------------------------------------------------------------------------
async def _run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async SQLAlchemy engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        future=True,
        connect_args={"statement_cache_size": 0},
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(_run_migrations_online())
