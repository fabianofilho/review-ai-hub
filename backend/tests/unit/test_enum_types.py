"""
Testes para PostgreSQLEnumType e mapeamento de ENUMs.

Verifica que:
1. PostgreSQLEnumType processa valores corretamente
2. Todos os ENUMs Python estão alinhados com PostgreSQL
3. Mapeamento POSTGRESQL_ENUM_VALUES está completo
"""

from enum import Enum as PyEnum

import pytest

# Importar todos os ENUMs Python para validação
from app.models.article import FileRole
from app.models.assessment import AssessmentSource, AssessmentStatus
from app.models.base import POSTGRESQL_ENUM_VALUES, PostgreSQLEnumType
from app.models.extraction import (
    ExtractionCardinality,
    ExtractionFieldType,
    ExtractionFramework,
    ExtractionInstanceStatus,
    ExtractionRunStage,
    ExtractionRunStatus,
    ExtractionSource,
    SuggestionStatus,
)
from app.models.project import ProjectMemberRole, ReviewType
from app.models.screening import (
    ScreeningConflictStatusValue,
    ScreeningDecisionValue,
    ScreeningPhase,
)


class TestPostgreSQLEnumType:
    """Testes para o TypeDecorator PostgreSQLEnumType."""

    def test_create_with_valid_enum_name(self):
        """Verifica criação com nome de enum válido."""
        enum_type = PostgreSQLEnumType("extraction_run_status")
        assert enum_type.enum_name == "extraction_run_status"

    def test_create_with_invalid_enum_name_raises(self):
        """Verifica que nome inválido levanta exceção."""
        with pytest.raises(ValueError) as exc_info:
            PostgreSQLEnumType("invalid_enum_name")

        assert "não registrado" in str(exc_info.value)
        assert "invalid_enum_name" in str(exc_info.value)

    def test_process_bind_param_with_string(self):
        """Verifica processamento de string."""
        enum_type = PostgreSQLEnumType("extraction_run_status")

        result = enum_type.process_bind_param("pending", None)
        assert result == "pending"

    def test_process_bind_param_with_enum(self):
        """Verifica processamento de Enum Python."""
        enum_type = PostgreSQLEnumType("extraction_run_status")

        result = enum_type.process_bind_param(ExtractionRunStatus.PENDING, None)
        assert result == "pending"

    def test_process_bind_param_with_none(self):
        """Verifica que None é mantido."""
        enum_type = PostgreSQLEnumType("extraction_run_status")

        result = enum_type.process_bind_param(None, None)
        assert result is None

    def test_process_result_value(self):
        """Verifica que valor do banco é retornado sem modificação."""
        enum_type = PostgreSQLEnumType("extraction_run_status")

        result = enum_type.process_result_value("completed", None)
        assert result == "completed"

    def test_cache_ok_is_true(self):
        """Verifica que cache está habilitado."""
        enum_type = PostgreSQLEnumType("extraction_run_status")
        assert enum_type.cache_ok is True


class TestPostgreSQLEnumValuesMapping:
    """Testes para o mapeamento POSTGRESQL_ENUM_VALUES."""

    def test_all_enums_are_registered(self):
        """Verifica que todos os ENUMs esperados estão registrados."""
        expected_enums = {
            "review_type",
            "project_member_role",
            "file_role",
            "extraction_framework",
            "extraction_field_type",
            "extraction_cardinality",
            "extraction_source",
            "extraction_run_stage",
            "extraction_run_status",
            "suggestion_status",
            "extraction_instance_status",
            "assessment_status",
            "assessment_source",
            "screening_phase",
            "screening_decision",
            "screening_conflict_status",
        }

        actual_enums = set(POSTGRESQL_ENUM_VALUES.keys())

        assert expected_enums == actual_enums

    def test_each_enum_has_values(self):
        """Verifica que cada enum tem pelo menos um valor."""
        for enum_name, values in POSTGRESQL_ENUM_VALUES.items():
            assert len(values) > 0, f"Enum '{enum_name}' não tem valores"
            assert all(isinstance(v, str) for v in values), (
                f"Enum '{enum_name}' tem valores não-string"
            )


class TestPythonEnumsMatchPostgreSQL:
    """Testes que verificam alinhamento entre ENUMs Python e PostgreSQL."""

    @pytest.mark.parametrize(
        "python_enum,postgres_enum_name",
        [
            (FileRole, "file_role"),
            (ReviewType, "review_type"),
            (ProjectMemberRole, "project_member_role"),
            (ExtractionFramework, "extraction_framework"),
            (ExtractionFieldType, "extraction_field_type"),
            (ExtractionCardinality, "extraction_cardinality"),
            (ExtractionSource, "extraction_source"),
            (ExtractionRunStage, "extraction_run_stage"),
            (ExtractionRunStatus, "extraction_run_status"),
            (SuggestionStatus, "suggestion_status"),
            (ExtractionInstanceStatus, "extraction_instance_status"),
            (AssessmentStatus, "assessment_status"),
            (AssessmentSource, "assessment_source"),
            (ScreeningPhase, "screening_phase"),
            (ScreeningDecisionValue, "screening_decision"),
            (ScreeningConflictStatusValue, "screening_conflict_status"),
        ],
    )
    def test_python_enum_matches_postgresql(
        self, python_enum: type[PyEnum], postgres_enum_name: str
    ):
        """Verifica que valores do Enum Python correspondem ao PostgreSQL."""
        # Valores do Python
        python_values = {e.value for e in python_enum}

        # Valores do PostgreSQL
        postgres_values = set(POSTGRESQL_ENUM_VALUES[postgres_enum_name])

        # Verificar que são iguais
        assert python_values == postgres_values, (
            f"Mismatch para {postgres_enum_name}:\n"
            f"  Python:     {sorted(python_values)}\n"
            f"  PostgreSQL: {sorted(postgres_values)}"
        )

    @pytest.mark.parametrize(
        "python_enum,postgres_enum_name",
        [
            (FileRole, "file_role"),
            (ReviewType, "review_type"),
            (ProjectMemberRole, "project_member_role"),
            (ExtractionFramework, "extraction_framework"),
            (ExtractionFieldType, "extraction_field_type"),
            (ExtractionCardinality, "extraction_cardinality"),
            (ExtractionSource, "extraction_source"),
            (ExtractionRunStage, "extraction_run_stage"),
            (ExtractionRunStatus, "extraction_run_status"),
            (SuggestionStatus, "suggestion_status"),
            (ExtractionInstanceStatus, "extraction_instance_status"),
            (AssessmentStatus, "assessment_status"),
            (AssessmentSource, "assessment_source"),
            (ScreeningPhase, "screening_phase"),
            (ScreeningDecisionValue, "screening_decision"),
            (ScreeningConflictStatusValue, "screening_conflict_status"),
        ],
    )
    def test_python_enum_is_str_subclass(self, python_enum: type[PyEnum], postgres_enum_name: str):
        """Verifica que todos os ENUMs Python herdam de str."""
        assert issubclass(python_enum, str), (
            f"{python_enum.__name__} deve herdar de str para compatibilidade com PostgreSQL"
        )


class TestEnumDefaults:
    """Testes para valores padrão dos ENUMs."""

    def test_extraction_instance_status_default(self):
        """Verifica valor padrão de ExtractionInstanceStatus."""
        assert ExtractionInstanceStatus.PENDING.value == "pending"

    def test_extraction_run_status_default(self):
        """Verifica valor padrão de ExtractionRunStatus."""
        assert ExtractionRunStatus.PENDING.value == "pending"

    def test_suggestion_status_default(self):
        """Verifica valor padrão de SuggestionStatus."""
        assert SuggestionStatus.PENDING.value == "pending"

    def test_assessment_status_default(self):
        """Verifica valor padrão de AssessmentStatus."""
        assert AssessmentStatus.IN_PROGRESS.value == "in_progress"

    def test_file_role_default(self):
        """Verifica valor padrão de FileRole."""
        assert FileRole.MAIN.value == "MAIN"

    def test_project_member_role_default(self):
        """Verifica valor padrão de ProjectMemberRole."""
        assert ProjectMemberRole.REVIEWER.value == "reviewer"

    def test_review_type_default(self):
        """Verifica valor padrão de ReviewType."""
        assert ReviewType.INTERVENTIONAL.value == "interventional"


class TestEnumCreationFromString:
    """Testes de criação de ENUMs a partir de strings."""

    @pytest.mark.parametrize(
        "python_enum,valid_value",
        [
            (FileRole, "MAIN"),
            (ReviewType, "interventional"),
            (ProjectMemberRole, "reviewer"),
            (ExtractionFramework, "CHARMS"),
            (ExtractionFieldType, "text"),
            (ExtractionCardinality, "one"),
            (ExtractionSource, "human"),
            (ExtractionRunStage, "data_suggest"),
            (ExtractionRunStatus, "pending"),
            (SuggestionStatus, "pending"),
            (ExtractionInstanceStatus, "pending"),
            (AssessmentStatus, "in_progress"),
            (AssessmentSource, "human"),
            (ScreeningPhase, "title_abstract"),
            (ScreeningDecisionValue, "include"),
            (ScreeningConflictStatusValue, "none"),
        ],
    )
    def test_enum_from_valid_string(self, python_enum: type[PyEnum], valid_value: str):
        """Verifica que podemos criar enum a partir de string válida."""
        instance = python_enum(valid_value)
        assert instance.value == valid_value

    @pytest.mark.parametrize(
        "python_enum",
        [
            FileRole,
            ReviewType,
            ProjectMemberRole,
            ExtractionFramework,
            ExtractionFieldType,
            ExtractionCardinality,
            ExtractionSource,
            ExtractionRunStage,
            ExtractionRunStatus,
            SuggestionStatus,
            ExtractionInstanceStatus,
            AssessmentStatus,
            AssessmentSource,
            ScreeningPhase,
            ScreeningDecisionValue,
            ScreeningConflictStatusValue,
        ],
    )
    def test_enum_from_invalid_string_raises(self, python_enum: type[PyEnum]):
        """Verifica que string inválida levanta ValueError."""
        with pytest.raises(ValueError):
            python_enum("totally_invalid_value_12345")
