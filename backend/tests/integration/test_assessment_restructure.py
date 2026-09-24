"""
Integration tests for restructured assessment module.

Tests the new assessment structure against real database:
- New tables (assessment_instances, assessment_responses, assessment_evidence)
- Compatibility VIEW (assessments)
- Helper functions (progress, hierarchy)
- Triggers (INSTEAD OF, validation)

These tests verify the migration was successful and everything works end-to-end.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
class TestAssessmentTablesExist:
    """Verify new tables were created."""

    async def test_assessment_instances_table_exists(self, db_session: AsyncSession) -> None:
        """Verify assessment_instances table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'assessment_instances'
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "assessment_instances"

    async def test_assessment_responses_table_exists(self, db_session: AsyncSession) -> None:
        """Verify assessment_responses table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'assessment_responses'
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "assessment_responses"

    async def test_assessment_evidence_table_exists(self, db_session: AsyncSession) -> None:
        """Verify assessment_evidence table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'assessment_evidence'
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "assessment_evidence"

    async def test_assessments_legacy_table_exists(self, db_session: AsyncSession) -> None:
        """Verify legacy table was renamed."""
        result = await db_session.execute(
            text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'assessments_legacy'
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "assessments_legacy"


@pytest.mark.asyncio
class TestAssessmentCompatibilityView:
    """Test backward compatibility VIEW."""

    async def test_assessments_view_exists(self, db_session: AsyncSession) -> None:
        """Verify assessments VIEW exists (compatibility layer)."""
        result = await db_session.execute(
            text("""
                SELECT table_name
                FROM information_schema.views
                WHERE table_schema = 'public'
                AND table_name = 'assessments'
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "assessments"

    async def test_view_has_correct_columns(self, db_session: AsyncSession) -> None:
        """Verify VIEW has same columns as old assessments table."""
        result = await db_session.execute(
            text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                AND table_name = 'assessments'
                ORDER BY ordinal_position
            """)
        )
        columns = [row[0] for row in result.fetchall()]

        # Should have old column names for compatibility
        expected_columns = [
            "id",
            "project_id",
            "article_id",
            "user_id",
            "responses",
            "overall_assessment",
            "notes",
            "status",
            "is_blind",
            "can_see_others",
            "metadata",
            "created_at",
            "updated_at",
        ]

        for col in expected_columns:
            assert col in columns, f"Missing column: {col}"

    async def test_view_can_be_queried(self, db_session: AsyncSession) -> None:
        """Verify VIEW can be queried like old table."""
        result = await db_session.execute(text("SELECT COUNT(*) FROM assessments"))
        row = result.fetchone()
        assert row is not None
        assert row[0] >= 0


@pytest.mark.asyncio
class TestAssessmentEnums:
    """Test new enum types."""

    async def test_assessment_source_enum_exists(self, db_session: AsyncSession) -> None:
        """Verify assessment_source enum was created."""
        result = await db_session.execute(
            text("""
                SELECT typname
                FROM pg_type
                WHERE typname = 'assessment_source'
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "assessment_source"

    async def test_assessment_source_enum_values(self, db_session: AsyncSession) -> None:
        """Verify enum has correct values."""
        result = await db_session.execute(
            text("""
                SELECT enumlabel
                FROM pg_enum
                WHERE enumtypid = (
                    SELECT oid FROM pg_type WHERE typname = 'assessment_source'
                )
                ORDER BY enumsortorder
            """)
        )
        values = [row[0] for row in result.fetchall()]
        assert values == ["human", "ai", "consensus"]


@pytest.mark.asyncio
class TestAssessmentIndexes:
    """Verify indexes were created for performance."""

    async def test_key_indexes_exist(self, db_session: AsyncSession) -> None:
        """Verify critical indexes exist."""
        # Get all indexes for assessment tables
        result = await db_session.execute(
            text("""
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                AND tablename IN ('assessment_instances', 'assessment_responses', 'assessment_evidence')
            """)
        )
        indexes = [row[0] for row in result.fetchall()]

        # Key indexes for performance
        expected_patterns = [
            "assessment_instances",  # At least primary key
            "assessment_responses",  # At least primary key
            "assessment_evidence",  # At least primary key
        ]

        for pattern in expected_patterns:
            matching = [idx for idx in indexes if pattern in idx]
            assert len(matching) > 0, f"No indexes found for {pattern}"


@pytest.mark.asyncio
class TestAssessmentFunctions:
    """Test helper SQL functions."""

    async def test_get_assessment_instance_children_function_exists(
        self, db_session: AsyncSession
    ) -> None:
        """Verify hierarchy helper function exists."""
        result = await db_session.execute(
            text("""
                SELECT proname
                FROM pg_proc
                WHERE proname = 'get_assessment_instance_children'
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "get_assessment_instance_children"

    async def test_calculate_assessment_instance_progress_function_exists(
        self, db_session: AsyncSession
    ) -> None:
        """Verify progress calculation function exists."""
        result = await db_session.execute(
            text("""
                SELECT proname
                FROM pg_proc
                WHERE proname = 'calculate_assessment_instance_progress'
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "calculate_assessment_instance_progress"

    async def test_rollback_function_exists(self, db_session: AsyncSession) -> None:
        """Verify rollback function exists."""
        result = await db_session.execute(
            text("""
                SELECT proname
                FROM pg_proc
                WHERE proname = 'rollback_assessment_restructure'
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "rollback_assessment_restructure"


@pytest.mark.asyncio
class TestAssessmentTriggers:
    """Test triggers for automation and validation."""

    async def test_updated_at_triggers_exist(self, db_session: AsyncSession) -> None:
        """Verify updated_at triggers exist."""
        result = await db_session.execute(
            text("""
                SELECT tgname
                FROM pg_trigger
                WHERE tgname LIKE '%updated_at%'
                AND tgrelid IN (
                    SELECT oid FROM pg_class
                    WHERE relname IN ('assessment_instances', 'assessment_responses')
                )
            """)
        )
        triggers = [row[0] for row in result.fetchall()]
        assert len(triggers) >= 2, "Should have updated_at triggers for both tables"

    async def test_view_instead_of_triggers_exist(self, db_session: AsyncSession) -> None:
        """Verify INSTEAD OF triggers for VIEW DML operations."""
        result = await db_session.execute(
            text("""
                SELECT tgname
                FROM pg_trigger
                WHERE tgrelid = (
                    SELECT oid FROM pg_class WHERE relname = 'assessments'
                )
            """)
        )
        triggers = [row[0] for row in result.fetchall()]

        # Should have INSERT, UPDATE, DELETE triggers
        trigger_names = [t.lower() for t in triggers]
        assert any("insert" in t for t in trigger_names), "Missing INSERT trigger"
        assert any("update" in t for t in trigger_names), "Missing UPDATE trigger"
        assert any("delete" in t for t in trigger_names), "Missing DELETE trigger"


@pytest.mark.asyncio
class TestAssessmentForeignKeys:
    """Test foreign key constraints."""

    async def test_instance_foreign_keys(self, db_session: AsyncSession) -> None:
        """Verify assessment_instances has correct foreign keys."""
        result = await db_session.execute(
            text("""
                SELECT
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_name = 'assessment_instances'
            """)
        )
        fks = {row[0]: row[1] for row in result.fetchall()}

        # Expected foreign keys
        assert "project_id" in fks
        assert "article_id" in fks
        assert "instrument_id" in fks
        assert "reviewer_id" in fks
        assert "extraction_instance_id" in fks
        assert "parent_instance_id" in fks

    async def test_response_foreign_keys(self, db_session: AsyncSession) -> None:
        """Verify assessment_responses has correct foreign keys."""
        result = await db_session.execute(
            text("""
                SELECT
                    kcu.column_name,
                    ccu.table_name AS foreign_table_name
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                    ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage AS ccu
                    ON ccu.constraint_name = tc.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_name = 'assessment_responses'
            """)
        )
        fks = {row[0]: row[1] for row in result.fetchall()}

        # Expected foreign keys
        assert "assessment_instance_id" in fks
        assert "assessment_item_id" in fks
        assert "reviewer_id" in fks
        assert "project_id" in fks
        assert "article_id" in fks


@pytest.mark.asyncio
class TestAssessmentWorkflow:
    """Test full workflow with real database operations."""

    async def test_can_count_instances(self, db_session: AsyncSession) -> None:
        """Test counting assessment instances."""
        result = await db_session.execute(text("SELECT COUNT(*) FROM assessment_instances"))
        row = result.fetchone()
        assert row is not None
        assert row[0] >= 0

    async def test_can_count_responses(self, db_session: AsyncSession) -> None:
        """Test counting assessment responses."""
        result = await db_session.execute(text("SELECT COUNT(*) FROM assessment_responses"))
        row = result.fetchone()
        assert row is not None
        assert row[0] >= 0

    async def test_can_count_evidence(self, db_session: AsyncSession) -> None:
        """Test counting assessment evidence."""
        result = await db_session.execute(text("SELECT COUNT(*) FROM assessment_evidence"))
        row = result.fetchone()
        assert row is not None
        assert row[0] >= 0

    async def test_can_join_instances_and_responses(self, db_session: AsyncSession) -> None:
        """Test joining instances with responses."""
        result = await db_session.execute(
            text("""
                SELECT
                    ai.id,
                    ai.label,
                    COUNT(ar.id) as response_count
                FROM assessment_instances ai
                LEFT JOIN assessment_responses ar ON ar.assessment_instance_id = ai.id
                GROUP BY ai.id, ai.label
                LIMIT 10
            """)
        )
        rows = result.fetchall()
        assert isinstance(rows, list)

    async def test_can_filter_by_source(self, db_session: AsyncSession) -> None:
        """Test filtering responses by source (human/ai/consensus)."""
        result = await db_session.execute(
            text("""
                SELECT source, COUNT(*)
                FROM assessment_responses
                GROUP BY source
            """)
        )
        rows = result.fetchall()
        assert isinstance(rows, list)

    async def test_can_query_hierarchy(self, db_session: AsyncSession) -> None:
        """Test querying parent-child relationships."""
        result = await db_session.execute(
            text("""
                SELECT
                    parent.id as parent_id,
                    parent.label as parent_label,
                    child.id as child_id,
                    child.label as child_label
                FROM assessment_instances parent
                LEFT JOIN assessment_instances child
                    ON child.parent_instance_id = parent.id
                WHERE parent.parent_instance_id IS NULL
                LIMIT 10
            """)
        )
        rows = result.fetchall()
        assert isinstance(rows, list)

    async def test_can_query_probast_per_model(self, db_session: AsyncSession) -> None:
        """Test querying assessments linked to extraction instances."""
        result = await db_session.execute(
            text("""
                SELECT
                    ai.id,
                    ai.label,
                    ai.extraction_instance_id,
                    ei.label as model_label
                FROM assessment_instances ai
                LEFT JOIN extraction_instances ei
                    ON ai.extraction_instance_id = ei.id
                WHERE ai.extraction_instance_id IS NOT NULL
                LIMIT 10
            """)
        )
        rows = result.fetchall()
        assert isinstance(rows, list)


@pytest.mark.asyncio
class TestAssessmentMigrationStatus:
    """Test migration tracking."""

    async def test_migration_status_table_exists(self, db_session: AsyncSession) -> None:
        """Verify migration status tracking table exists."""
        result = await db_session.execute(
            text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = 'assessment_migration_status'
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "assessment_migration_status"

    async def test_migration_marked_complete(self, db_session: AsyncSession) -> None:
        """Verify migration is marked as completed."""
        result = await db_session.execute(
            text("""
                SELECT status, completed_at
                FROM assessment_migration_status
                WHERE id = 1
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "completed"
        assert row[1] is not None  # Should have completion timestamp


@pytest.mark.asyncio
class TestAssessmentCheckConstraints:
    """Test check constraints for data integrity."""

    async def test_instance_has_check_constraints(self, db_session: AsyncSession) -> None:
        """Verify assessment_instances has check constraints."""
        result = await db_session.execute(
            text("""
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = (
                    SELECT oid FROM pg_class WHERE relname = 'assessment_instances'
                )
                AND contype = 'c'
            """)
        )
        constraints = [row[0] for row in result.fetchall()]

        # Should have constraint preventing extraction_instance_id on non-root
        assert any("extraction" in c.lower() for c in constraints), (
            "Missing extraction_instance_id constraint"
        )


@pytest.mark.asyncio
class TestAssessmentPerformance:
    """Test performance-related features."""

    async def test_article_id_denormalization(self, db_session: AsyncSession) -> None:
        """Verify article_id is denormalized in responses for RLS performance."""
        result = await db_session.execute(
            text("""
                SELECT column_name, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'assessment_responses'
                AND column_name = 'article_id'
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "article_id"
        assert row[1] == "NO"  # NOT NULL

    async def test_indexes_cover_common_queries(self, db_session: AsyncSession) -> None:
        """Verify indexes exist for common query patterns."""
        # Check for index on (article_id, assessment_item_id) for fast lookups
        result = await db_session.execute(
            text("""
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'assessment_responses'
                AND indexdef LIKE '%article_id%'
            """)
        )
        indexes = [row[0] for row in result.fetchall()]
        assert len(indexes) > 0, "Missing index on article_id for responses"


@pytest.mark.asyncio
class TestBackwardCompatibility:
    """Test that old code patterns still work via VIEW."""

    async def test_can_select_from_assessments_view(self, db_session: AsyncSession) -> None:
        """Test SELECT works on compatibility VIEW."""
        result = await db_session.execute(
            text("""
                SELECT id, project_id, article_id, responses, status
                FROM assessments
                LIMIT 5
            """)
        )
        rows = result.fetchall()
        assert isinstance(rows, list)

    async def test_view_responses_column_is_jsonb(self, db_session: AsyncSession) -> None:
        """Verify responses column in VIEW is JSONB type."""
        result = await db_session.execute(
            text("""
                SELECT data_type
                FROM information_schema.columns
                WHERE table_name = 'assessments'
                AND column_name = 'responses'
            """)
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "jsonb"

    async def test_view_aggregates_responses_correctly(self, db_session: AsyncSession) -> None:
        """Test VIEW correctly aggregates responses back to JSONB."""
        # This query should work without errors (even if no data)
        result = await db_session.execute(
            text("""
                SELECT
                    id,
                    responses,
                    jsonb_typeof(responses) as responses_type
                FROM assessments
                WHERE responses IS NOT NULL
                LIMIT 1
            """)
        )
        row = result.fetchone()

        if row:  # If there's data
            assert row[2] == "object", "responses should be a JSON object"
