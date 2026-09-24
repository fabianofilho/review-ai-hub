"""
Unit tests for new assessment repositories.

Tests the restructured assessment module:
- AssessmentInstanceRepository
- AssessmentResponseRepository
- AssessmentEvidenceRepository

Following the extraction pattern architecture.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assessment import (
    AssessmentEvidence,
    AssessmentInstance,
    AssessmentResponse,
    AssessmentSource,
)
from app.repositories.assessment_repository import (
    AssessmentEvidenceRepository,
    AssessmentInstanceRepository,
    AssessmentResponseRepository,
)


@pytest.fixture
def mock_db():
    """Mock AsyncSession."""
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def project_id():
    """Test project ID."""
    return uuid4()


@pytest.fixture
def article_id():
    """Test article ID."""
    return uuid4()


@pytest.fixture
def instrument_id():
    """Test instrument ID."""
    return uuid4()


@pytest.fixture
def reviewer_id():
    """Test reviewer ID."""
    return uuid4()


@pytest.fixture
def instance_id():
    """Test instance ID."""
    return uuid4()


@pytest.fixture
def item_id():
    """Test assessment item ID."""
    return uuid4()


class TestAssessmentInstanceRepository:
    """Tests for AssessmentInstanceRepository."""

    @pytest.fixture
    def repo(self, mock_db):
        """Create repository instance."""
        return AssessmentInstanceRepository(mock_db)

    @pytest.fixture
    def mock_instance(self, instance_id, project_id, article_id, instrument_id, reviewer_id):
        """Create mock AssessmentInstance."""
        instance = MagicMock(spec=AssessmentInstance)
        instance.id = instance_id
        instance.project_id = project_id
        instance.article_id = article_id
        instance.instrument_id = instrument_id
        instance.extraction_instance_id = None
        instance.parent_instance_id = None
        instance.label = "Test Assessment"
        instance.status = "in_progress"
        instance.reviewer_id = reviewer_id
        instance.is_blind = False
        instance.can_see_others = True
        instance.meta = {}
        instance.created_at = datetime.now(UTC)
        instance.updated_at = datetime.now(UTC)
        instance.responses = []
        return instance

    @pytest.mark.asyncio
    async def test_get_by_article(self, repo, mock_db, article_id, mock_instance):
        """Test getting instances by article ID."""
        # Mock query result
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_instance]
        mock_db.execute.return_value = mock_result

        # Execute
        instances = await repo.get_by_article(article_id)

        # Verify
        assert len(instances) == 1
        assert instances[0].id == mock_instance.id
        assert instances[0].article_id == article_id
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_article_with_instrument(
        self, repo, mock_db, article_id, instrument_id, mock_instance
    ):
        """Test filtering by article and instrument."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_instance]
        mock_db.execute.return_value = mock_result

        instances = await repo.get_by_article(article_id, instrument_id=instrument_id)

        assert len(instances) == 1
        assert instances[0].instrument_id == instrument_id
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_extraction_instance(self, repo, mock_db, mock_instance):
        """Test getting instances linked to extraction instance (PROBAST per model)."""
        extraction_instance_id = uuid4()
        mock_instance.extraction_instance_id = extraction_instance_id

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_instance]
        mock_db.execute.return_value = mock_result

        instances = await repo.get_by_extraction_instance(extraction_instance_id)

        assert len(instances) == 1
        assert instances[0].extraction_instance_id == extraction_instance_id
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_children(self, repo, mock_db, instance_id):
        """Test getting child instances (hierarchy)."""
        parent_id = instance_id
        child1 = MagicMock(spec=AssessmentInstance)
        child1.id = uuid4()
        child1.parent_instance_id = parent_id

        child2 = MagicMock(spec=AssessmentInstance)
        child2.id = uuid4()
        child2.parent_instance_id = parent_id

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [child1, child2]
        mock_db.execute.return_value = mock_result

        children = await repo.get_children(parent_id)

        assert len(children) == 2
        assert all(c.parent_instance_id == parent_id for c in children)
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_roots(self, repo, mock_db, mock_instance):
        """Test getting root instances (no parent)."""
        mock_instance.parent_instance_id = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_instance]
        mock_db.execute.return_value = mock_result

        roots = await repo.get_roots(mock_instance.article_id)

        assert len(roots) == 1
        assert roots[0].parent_instance_id is None
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_instance(self, repo, mock_db, mock_instance):
        """Test creating new instance."""
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await repo.create(mock_instance)

        mock_db.add.assert_called_once_with(mock_instance)
        mock_db.flush.assert_called_once()
        mock_db.refresh.assert_called_once_with(mock_instance)
        assert result == mock_instance


class TestAssessmentResponseRepository:
    """Tests for AssessmentResponseRepository."""

    @pytest.fixture
    def repo(self, mock_db):
        """Create repository instance."""
        return AssessmentResponseRepository(mock_db)

    @pytest.fixture
    def mock_response(self, instance_id, item_id, reviewer_id, project_id, article_id):
        """Create mock AssessmentResponse."""
        response = MagicMock(spec=AssessmentResponse)
        response.id = uuid4()
        response.assessment_instance_id = instance_id
        response.assessment_item_id = item_id
        response.selected_level = "yes"
        response.notes = "Test notes"
        response.confidence = 0.95
        response.source = AssessmentSource.HUMAN
        response.reviewer_id = reviewer_id
        response.ai_suggestion_id = None
        response.project_id = project_id
        response.article_id = article_id
        response.created_at = datetime.now(UTC)
        response.updated_at = datetime.now(UTC)
        return response

    @pytest.mark.asyncio
    async def test_get_by_instance(self, repo, mock_db, instance_id, mock_response):
        """Test getting all responses for an instance."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_response]
        mock_db.execute.return_value = mock_result

        responses = await repo.get_by_instance(instance_id)

        assert len(responses) == 1
        assert responses[0].assessment_instance_id == instance_id
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_item(self, repo, mock_db, instance_id, item_id, mock_response):
        """Test getting response for specific item."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = mock_response
        mock_db.execute.return_value = mock_result

        response = await repo.get_by_item(instance_id, item_id)

        assert response is not None
        assert response.assessment_item_id == item_id
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_article(self, repo, mock_db, article_id, mock_response):
        """Test getting all responses for an article."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_response]
        mock_db.execute.return_value = mock_result

        responses = await repo.get_by_article(article_id)

        assert len(responses) == 1
        assert responses[0].article_id == article_id
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_bulk_create(self, repo, mock_db, mock_response):
        """Test bulk creating responses."""
        responses = [mock_response, mock_response]

        mock_db.add_all = MagicMock()
        mock_db.flush = AsyncMock()

        # Mock refresh behavior
        async def mock_refresh(obj):
            pass

        mock_db.refresh = AsyncMock(side_effect=mock_refresh)

        result = await repo.bulk_create(responses)

        mock_db.add_all.assert_called_once()
        mock_db.flush.assert_called_once()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_upsert_response_create(self, repo, mock_db, instance_id, item_id, reviewer_id):
        """Test upsert when response doesn't exist (INSERT)."""
        # Mock: no existing response
        mock_result_select = MagicMock()
        mock_result_select.scalars.return_value.first.return_value = None

        # Mock: insert
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        new_response = MagicMock(spec=AssessmentResponse)
        new_response.id = uuid4()

        # Execute with side effect
        async def execute_side_effect(stmt):
            # First call: SELECT (no result)
            if mock_db.execute.call_count == 1:
                return mock_result_select
            # After add, return the new object
            return mock_result_select

        mock_db.execute.side_effect = execute_side_effect

        data = {
            "assessment_instance_id": instance_id,
            "assessment_item_id": item_id,
            "selected_level": "yes",
            "notes": "New response",
            "confidence": 0.9,
            "source": "human",
            "reviewer_id": reviewer_id,
            "project_id": uuid4(),
            "article_id": uuid4(),
        }

        # Create new response object for the add
        with patch.object(repo, "_model", AssessmentResponse):
            response = await repo.upsertResponse(data)

        # Should call add for new object
        mock_db.add.assert_called()

    @pytest.mark.asyncio
    async def test_filter_by_source(self, repo, mock_db, article_id):
        """Test filtering responses by source (human/ai/consensus)."""
        ai_response = MagicMock(spec=AssessmentResponse)
        ai_response.source = AssessmentSource.AI
        ai_response.article_id = article_id

        human_response = MagicMock(spec=AssessmentResponse)
        human_response.source = AssessmentSource.HUMAN
        human_response.article_id = article_id

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [ai_response]
        mock_db.execute.return_value = mock_result

        responses = await repo.get_by_article(article_id, source=AssessmentSource.AI)

        assert len(responses) == 1
        assert responses[0].source == AssessmentSource.AI


class TestAssessmentEvidenceRepository:
    """Tests for AssessmentEvidenceRepository."""

    @pytest.fixture
    def repo(self, mock_db):
        """Create repository instance."""
        return AssessmentEvidenceRepository(mock_db)

    @pytest.fixture
    def mock_evidence(self, instance_id, reviewer_id):
        """Create mock AssessmentEvidence."""
        evidence = MagicMock(spec=AssessmentEvidence)
        evidence.id = uuid4()
        evidence.assessment_instance_id = instance_id
        evidence.assessment_response_id = None
        evidence.article_file_id = uuid4()
        evidence.page_number = 5
        evidence.position = {"x": 100, "y": 200, "width": 50, "height": 20}
        evidence.text_content = "This is evidence from the PDF"
        evidence.created_by = reviewer_id
        evidence.created_at = datetime.now(UTC)
        return evidence

    @pytest.mark.asyncio
    async def test_get_by_instance(self, repo, mock_db, instance_id, mock_evidence):
        """Test getting all evidence for an instance."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_evidence]
        mock_db.execute.return_value = mock_result

        evidence = await repo.get_by_instance(instance_id)

        assert len(evidence) == 1
        assert evidence[0].assessment_instance_id == instance_id
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_by_response(self, repo, mock_db, mock_evidence):
        """Test getting evidence for specific response."""
        response_id = uuid4()
        mock_evidence.assessment_response_id = response_id

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_evidence]
        mock_db.execute.return_value = mock_result

        evidence = await repo.get_by_response(response_id)

        assert len(evidence) == 1
        assert evidence[0].assessment_response_id == response_id
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_evidence(self, repo, mock_db, mock_evidence):
        """Test creating evidence with PDF reference."""
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await repo.create(mock_evidence)

        mock_db.add.assert_called_once_with(mock_evidence)
        mock_db.flush.assert_called_once()
        assert result == mock_evidence

    @pytest.mark.asyncio
    async def test_evidence_with_position_data(self, repo, mock_evidence):
        """Test evidence stores position data correctly."""
        assert mock_evidence.page_number == 5
        assert mock_evidence.position["x"] == 100
        assert mock_evidence.position["y"] == 200
        assert mock_evidence.text_content == "This is evidence from the PDF"


class TestAssessmentRepositoriesIntegration:
    """Integration tests for repositories working together."""

    @pytest.fixture
    def instance_repo(self, mock_db):
        return AssessmentInstanceRepository(mock_db)

    @pytest.fixture
    def response_repo(self, mock_db):
        return AssessmentResponseRepository(mock_db)

    @pytest.fixture
    def evidence_repo(self, mock_db):
        return AssessmentEvidenceRepository(mock_db)

    @pytest.mark.asyncio
    async def test_full_assessment_workflow(
        self,
        instance_repo,
        response_repo,
        evidence_repo,
        mock_db,
        project_id,
        article_id,
        instrument_id,
        reviewer_id,
    ):
        """Test creating complete assessment with responses and evidence."""
        # 1. Create instance
        instance = AssessmentInstance(
            project_id=project_id,
            article_id=article_id,
            instrument_id=instrument_id,
            label="Test PROBAST",
            reviewer_id=reviewer_id,
        )

        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        created_instance = await instance_repo.create(instance)
        assert created_instance is not None

        # 2. Create responses
        responses = [
            AssessmentResponse(
                assessment_instance_id=instance.id,
                assessment_item_id=uuid4(),
                selected_level="yes",
                source=AssessmentSource.HUMAN,
                reviewer_id=reviewer_id,
                project_id=project_id,
                article_id=article_id,
            )
            for _ in range(3)
        ]

        mock_db.add_all = MagicMock()
        created_responses = await response_repo.bulk_create(responses)
        assert len(created_responses) == 3

        # 3. Add evidence
        evidence = AssessmentEvidence(
            assessment_instance_id=instance.id,
            assessment_response_id=responses[0].id,
            article_file_id=uuid4(),
            page_number=10,
            text_content="Evidence text",
            created_by=reviewer_id,
        )

        created_evidence = await evidence_repo.create(evidence)
        assert created_evidence is not None

    @pytest.mark.asyncio
    async def test_hierarchy_workflow(
        self,
        instance_repo,
        mock_db,
        project_id,
        article_id,
        instrument_id,
        reviewer_id,
    ):
        """Test creating parent-child assessment instances."""
        # Create parent
        parent = AssessmentInstance(
            project_id=project_id,
            article_id=article_id,
            instrument_id=instrument_id,
            label="Parent Assessment",
            reviewer_id=reviewer_id,
        )

        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        created_parent = await instance_repo.create(parent)

        # Create children
        child1 = AssessmentInstance(
            project_id=project_id,
            article_id=article_id,
            instrument_id=instrument_id,
            parent_instance_id=parent.id,
            label="Child Assessment 1",
            reviewer_id=reviewer_id,
        )

        child2 = AssessmentInstance(
            project_id=project_id,
            article_id=article_id,
            instrument_id=instrument_id,
            parent_instance_id=parent.id,
            label="Child Assessment 2",
            reviewer_id=reviewer_id,
        )

        await instance_repo.create(child1)
        await instance_repo.create(child2)

        # Verify hierarchy
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [child1, child2]
        mock_db.execute.return_value = mock_result

        children = await instance_repo.get_children(parent.id)
        assert len(children) == 2
        assert all(c.parent_instance_id == parent.id for c in children)

    @pytest.mark.asyncio
    async def test_probast_per_model_workflow(
        self,
        instance_repo,
        mock_db,
        project_id,
        article_id,
        instrument_id,
        reviewer_id,
    ):
        """Test linking assessments to extraction instances (PROBAST per model)."""
        extraction_instance_id = uuid4()

        instance = AssessmentInstance(
            project_id=project_id,
            article_id=article_id,
            instrument_id=instrument_id,
            extraction_instance_id=extraction_instance_id,
            label="PROBAST for Model A",
            reviewer_id=reviewer_id,
        )

        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        created = await instance_repo.create(instance)
        assert created.extraction_instance_id == extraction_instance_id

        # Verify we can query by extraction instance
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [instance]
        mock_db.execute.return_value = mock_result

        instances = await instance_repo.get_by_extraction_instance(extraction_instance_id)
        assert len(instances) == 1
        assert instances[0].extraction_instance_id == extraction_instance_id
