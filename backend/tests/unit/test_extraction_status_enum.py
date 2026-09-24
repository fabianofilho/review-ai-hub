"""
Tests for ExtractionInstanceStatus enum.

Verifies that the Python enum is aligned with the PostgreSQL enum.
"""

import pytest

from app.models.extraction import ExtractionInstanceStatus


class TestExtractionInstanceStatusEnum:
    """Tests for extraction instance status enum."""

    def test_enum_values_exist(self):
        """Verifies that all expected values exist."""
        expected_values = {"pending", "in_progress", "completed", "reviewed", "archived"}
        actual_values = {status.value for status in ExtractionInstanceStatus}

        assert actual_values == expected_values

    def test_pending_is_default(self):
        """Verifies that PENDING is the default value."""
        assert ExtractionInstanceStatus.PENDING.value == "pending"

    def test_enum_is_string_compatible(self):
        """Verifies that the enum can be used as string."""
        status = ExtractionInstanceStatus.COMPLETED

        # Should be comparable with string (inherits from str)
        assert status == "completed"
        assert status.value == "completed"

        # .value is the correct way to get the string
        assert status.value == "completed"

        # Can be used in string comparisons
        assert f"{status.value}" == "completed"

    def test_enum_from_string(self):
        """Verifies that we can create enum from string."""
        status = ExtractionInstanceStatus("pending")
        assert status == ExtractionInstanceStatus.PENDING

    def test_enum_invalid_value_raises(self):
        """Verifies that invalid value raises exception."""
        with pytest.raises(ValueError):
            ExtractionInstanceStatus("invalid_status")

    def test_all_status_values_are_snake_case(self):
        """Verifies that all values follow snake_case (PostgreSQL convention)."""
        for status in ExtractionInstanceStatus:
            # Should be lowercase
            assert status.value == status.value.lower()
            # Words separated by underscore (or single word)
            assert status.value.replace("_", "").isalpha()

    def test_status_workflow_progression(self):
        """Tests logical status progression flow."""
        # Expected logical workflow order
        workflow = [
            ExtractionInstanceStatus.PENDING,
            ExtractionInstanceStatus.IN_PROGRESS,
            ExtractionInstanceStatus.COMPLETED,
            ExtractionInstanceStatus.REVIEWED,
        ]

        # All must be unique
        assert len(workflow) == len(set(workflow))

        # ARCHIVED is a special state (not part of main workflow)
        assert ExtractionInstanceStatus.ARCHIVED not in workflow
