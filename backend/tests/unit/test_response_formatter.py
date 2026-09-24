"""
Unit tests for app.utils.response_formatter.

Covers snake_case and camelCase conversion of strings and nested payloads,
and the extraction response builders used by the extraction endpoints.
"""

import pytest

from app.utils.response_formatter import (
    dict_to_camel_case,
    dict_to_snake_case,
    format_extraction_response,
    format_model_extraction_response,
    format_section_extraction_response,
    to_camel_case,
    to_snake_case,
)


class TestToCamelCase:
    @pytest.mark.parametrize(
        ("snake", "camel"),
        [
            ("entity_type_id", "entityTypeId"),
            ("created_at", "createdAt"),
            ("name", "name"),
            ("a_b_c", "aBC"),
            ("", ""),
        ],
    )
    def test_converts(self, snake: str, camel: str) -> None:
        assert to_camel_case(snake) == camel

    def test_camel_input_is_unchanged(self) -> None:
        assert to_camel_case("entityTypeId") == "entityTypeId"


class TestToSnakeCase:
    @pytest.mark.parametrize(
        ("camel", "snake"),
        [
            ("entityTypeId", "entity_type_id"),
            ("createdAt", "created_at"),
            ("name", "name"),
            ("EntityType", "entity_type"),
        ],
    )
    def test_converts(self, camel: str, snake: str) -> None:
        assert to_snake_case(camel) == snake

    def test_snake_input_is_unchanged(self) -> None:
        assert to_snake_case("already_snake") == "already_snake"


class TestDictToCamelCase:
    def test_converts_nested_dicts_and_lists(self) -> None:
        data = {
            "article_id": "a1",
            "extraction_meta": {"model_name": "gpt", "token_usage": {"prompt_tokens": 3}},
            "field_values": [{"field_id": "f1", "raw_value": 1}, "plain_string", 7],
            "empty_list": [],
            "none_value": None,
        }

        assert dict_to_camel_case(data) == {
            "articleId": "a1",
            "extractionMeta": {"modelName": "gpt", "tokenUsage": {"promptTokens": 3}},
            "fieldValues": [{"fieldId": "f1", "rawValue": 1}, "plain_string", 7],
            "emptyList": [],
            "noneValue": None,
        }

    def test_does_not_mutate_input(self) -> None:
        data = {"outer_key": {"inner_key": 1}}

        dict_to_camel_case(data)

        assert data == {"outer_key": {"inner_key": 1}}

    def test_empty_dict(self) -> None:
        assert dict_to_camel_case({}) == {}


class TestDictToSnakeCase:
    def test_converts_nested_dicts_and_lists(self) -> None:
        data = {
            "articleId": "a1",
            "extractionMeta": {"modelName": "gpt"},
            "fieldValues": [{"fieldId": "f1"}, "plainString", 7],
            "count": 2,
        }

        assert dict_to_snake_case(data) == {
            "article_id": "a1",
            "extraction_meta": {"model_name": "gpt"},
            "field_values": [{"field_id": "f1"}, "plainString", 7],
            "count": 2,
        }

    def test_round_trip_with_camel_case(self) -> None:
        original = {"entity_type_id": 1, "nested_value": [{"inner_key": True}]}

        assert dict_to_snake_case(dict_to_camel_case(original)) == original


class TestFormatExtractionResponse:
    def test_only_created_count(self) -> None:
        assert format_extraction_response(created_count=0) == {"createdCount": 0}

    def test_includes_all_optional_sections(self) -> None:
        result = format_extraction_response(
            created_count=2,
            suggestions=[{"field_id": "f1", "suggested_value": {"raw_text": "x"}}, "keep-me"],
            models=[{"model_name": "M1", "model_type": "logistic"}],
            error="partial failure",
        )

        assert result == {
            "createdCount": 2,
            "suggestions": [{"fieldId": "f1", "suggestedValue": {"rawText": "x"}}, "keep-me"],
            "models": [{"modelName": "M1", "modelType": "logistic"}],
            "error": "partial failure",
        }

    def test_empty_lists_are_kept(self) -> None:
        result = format_extraction_response(created_count=0, suggestions=[], models=[])

        assert result == {"createdCount": 0, "suggestions": [], "models": []}

    def test_error_only(self) -> None:
        result = format_extraction_response(created_count=0, error="no text")

        assert result == {"createdCount": 0, "error": "no text"}
        assert "suggestions" not in result
        assert "models" not in result


class TestFormatModelExtractionResponse:
    def test_formats_models(self) -> None:
        result = format_model_extraction_response(
            models_count=2,
            models=[
                {"model_name": "A", "predictor_list": [{"var_name": "age"}]},
                "raw-entry",
            ],
        )

        assert result == {
            "modelsCount": 2,
            "models": [{"modelName": "A", "predictorList": [{"varName": "age"}]}, "raw-entry"],
        }

    def test_empty_models(self) -> None:
        assert format_model_extraction_response(models_count=0, models=[]) == {
            "modelsCount": 0,
            "models": [],
        }


class TestFormatSectionExtractionResponse:
    def test_formats_suggestions(self) -> None:
        result = format_section_extraction_response(
            created_count=1,
            suggestions=[{"instance_id": "i1", "confidence_score": 0.9}, 5],
        )

        assert result == {
            "createdCount": 1,
            "suggestions": [{"instanceId": "i1", "confidenceScore": 0.9}, 5],
        }
