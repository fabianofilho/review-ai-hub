"""
Mapper tests for the ScreeningRun ORM relationships.

ScreeningRun.suggestions must be a one-to-many collection: a screening run
owns many AI suggestions through ai_suggestions.screening_run_id. A bare
``Mapped[list]`` annotation once made SQLAlchemy map it as a scalar
(uselist=False), so these tests pin the collection semantics.
"""

from sqlalchemy import inspect
from sqlalchemy.orm import RelationshipDirection, configure_mappers

import app.models  # noqa: F401  (registers every mapped class)
from app.models.extraction import AISuggestion
from app.models.screening import ScreeningRun


def test_screening_run_suggestions_is_one_to_many_list() -> None:
    """ScreeningRun.suggestions is mapped as a list collection of AISuggestion."""
    configure_mappers()
    prop = inspect(ScreeningRun).relationships["suggestions"]

    assert prop.uselist is True
    assert prop.collection_class is list
    assert prop.direction is RelationshipDirection.ONETOMANY
    assert prop.mapper.class_ is AISuggestion
    assert {(col.table.name, col.name) for col in prop.remote_side} == {
        ("ai_suggestions", "screening_run_id")
    }


def test_new_screening_run_has_empty_suggestions_list() -> None:
    """A transient ScreeningRun exposes an empty list, not None."""
    run = ScreeningRun()

    assert run.suggestions == []
