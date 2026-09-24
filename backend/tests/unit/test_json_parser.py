"""
Unit tests for app.utils.json_parser.

Covers extraction of JSON from raw and markdown-wrapped LLM output, the
object and array parsers with and without defaults, and model extraction.
"""

import json
from unittest.mock import patch

import pytest

from app.utils.json_parser import (
    JSONParseError,
    _extract_json_from_markdown,
    extract_models_from_response,
    parse_json_array_safe,
    parse_json_safe,
)


class TestJSONParseError:
    def test_keeps_message_and_original_content(self) -> None:
        err = JSONParseError("boom", original_content="raw text")

        assert str(err) == "boom"
        assert err.original_content == "raw text"

    def test_original_content_defaults_to_none(self) -> None:
        assert JSONParseError("boom").original_content is None


class TestExtractJsonFromMarkdown:
    def test_extracts_from_json_fenced_block(self) -> None:
        content = 'Here you go:\n```json\n{"a": 1}\n```\nThanks'

        assert _extract_json_from_markdown(content) == '{"a": 1}'

    def test_extracts_from_unlabelled_fenced_block(self) -> None:
        content = "```\n[1, 2, 3]\n```"

        assert _extract_json_from_markdown(content) == "[1, 2, 3]"

    def test_returns_stripped_raw_object(self) -> None:
        assert _extract_json_from_markdown('  \n{"a": 1}\n  ') == '{"a": 1}'

    def test_returns_stripped_raw_array(self) -> None:
        assert _extract_json_from_markdown("  [1, 2]  ") == "[1, 2]"

    def test_skips_leading_prose_before_object(self) -> None:
        assert _extract_json_from_markdown('Result: {"a": 1}') == '{"a": 1}'

    def test_skips_leading_prose_before_array(self) -> None:
        assert _extract_json_from_markdown("The list is [1, 2]") == "[1, 2]"

    def test_returns_text_unchanged_when_no_json_marker(self) -> None:
        assert _extract_json_from_markdown("  no json here  ") == "no json here"


class TestParseJsonSafe:
    def test_parses_raw_object(self) -> None:
        assert parse_json_safe('{"a": 1, "b": [true, null]}') == {"a": 1, "b": [True, None]}

    def test_parses_markdown_wrapped_object(self) -> None:
        content = '```json\n{"models": [{"name": "m1"}]}\n```'

        assert parse_json_safe(content) == {"models": [{"name": "m1"}]}

    @pytest.mark.parametrize("content", ["", "   \n\t"])
    def test_empty_content_raises(self, content: str) -> None:
        with pytest.raises(JSONParseError, match="Empty JSON content") as exc_info:
            parse_json_safe(content)

        assert exc_info.value.original_content == content

    def test_empty_content_returns_default(self) -> None:
        default = {"fallback": True}

        with patch("app.utils.json_parser.logger") as mock_logger:
            result = parse_json_safe("", default=default, trace_id="t-1")

        assert result is default
        mock_logger.warning.assert_called_once_with(
            "Empty JSON received, using default", trace_id="t-1"
        )

    def test_empty_dict_default_is_honoured(self) -> None:
        # An empty dict is a valid default: only None means "raise".
        assert parse_json_safe("", default={}) == {}

    def test_invalid_json_raises_with_cause(self) -> None:
        with pytest.raises(JSONParseError, match="Invalid JSON") as exc_info:
            parse_json_safe('{"a": 1,}')

        assert exc_info.value.original_content == '{"a": 1,}'
        assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)

    def test_invalid_json_returns_default_and_logs(self) -> None:
        default = {"x": 0}

        with patch("app.utils.json_parser.logger") as mock_logger:
            result = parse_json_safe("{not json", default=default, trace_id="t-2")

        assert result is default
        mock_logger.error.assert_called_once()
        args, kwargs = mock_logger.error.call_args
        assert args == ("Failed to parse JSON",)
        assert kwargs["trace_id"] == "t-2"
        assert kwargs["content_preview"] == "{not json"

    def test_error_log_preview_is_truncated_to_200_chars(self) -> None:
        content = "{" + "x" * 500

        with patch("app.utils.json_parser.logger") as mock_logger:
            parse_json_safe(content, default={})

        assert mock_logger.error.call_args.kwargs["content_preview"] == content[:200]

    def test_top_level_list_is_wrapped_in_items(self) -> None:
        assert parse_json_safe("[1, 2]") == {"items": [1, 2]}

    def test_top_level_list_is_wrapped_even_with_default(self) -> None:
        assert parse_json_safe('[{"a": 1}]', default={"d": 1}) == {"items": [{"a": 1}]}

    @pytest.mark.parametrize(
        ("content", "type_name"),
        [("42", "int"), ('"text"', "str"), ("true", "bool"), ("null", "NoneType")],
    )
    def test_scalar_raises_without_default(self, content: str, type_name: str) -> None:
        with pytest.raises(JSONParseError, match=f"got {type_name}") as exc_info:
            parse_json_safe(content)

        assert exc_info.value.original_content == content

    def test_scalar_returns_default(self) -> None:
        default = {"d": 1}

        assert parse_json_safe("42", default=default) is default

    def test_missing_expected_keys_logs_warning_but_returns_result(self) -> None:
        with patch("app.utils.json_parser.logger") as mock_logger:
            result = parse_json_safe(
                '{"a": 1, "b": 2}', expected_keys=["a", "c", "d"], trace_id="t-3"
            )

        assert result == {"a": 1, "b": 2}
        mock_logger.warning.assert_called_once_with(
            "JSON missing expected keys",
            missing_keys=["c", "d"],
            available_keys=["a", "b"],
            trace_id="t-3",
        )

    def test_present_expected_keys_do_not_log(self) -> None:
        with patch("app.utils.json_parser.logger") as mock_logger:
            result = parse_json_safe('{"a": 1}', expected_keys=["a"])

        assert result == {"a": 1}
        mock_logger.warning.assert_not_called()


class TestParseJsonArraySafe:
    def test_parses_raw_array(self) -> None:
        assert parse_json_array_safe('[{"a": 1}, {"a": 2}]') == [{"a": 1}, {"a": 2}]

    def test_parses_markdown_wrapped_array(self) -> None:
        assert parse_json_array_safe("```json\n[1, 2]\n```") == [1, 2]

    @pytest.mark.parametrize("key", ["items", "models", "data"])
    def test_unwraps_known_container_keys(self, key: str) -> None:
        content = json.dumps({key: [1, 2], "meta": {"count": 2}})

        assert parse_json_array_safe(content) == [1, 2]

    def test_items_key_takes_precedence(self) -> None:
        content = json.dumps({"data": ["d"], "models": ["m"], "items": ["i"]})

        assert parse_json_array_safe(content) == ["i"]

    def test_models_key_takes_precedence_over_data(self) -> None:
        content = json.dumps({"data": ["d"], "models": ["m"]})

        assert parse_json_array_safe(content) == ["m"]

    def test_falls_back_to_first_list_value(self) -> None:
        content = json.dumps({"count": 2, "results": ["r1", "r2"], "other": ["o"]})

        assert parse_json_array_safe(content) == ["r1", "r2"]

    def test_dict_without_list_raises(self) -> None:
        with pytest.raises(JSONParseError, match="JSON expected as array, got dict"):
            parse_json_array_safe('{"a": 1}')

    def test_known_key_with_non_list_value_raises(self) -> None:
        with pytest.raises(JSONParseError, match="got int"):
            parse_json_array_safe('{"items": 5}')

    def test_non_list_returns_default(self) -> None:
        default = ["fallback"]

        with patch("app.utils.json_parser.logger") as mock_logger:
            result = parse_json_array_safe('{"a": 1}', default=default, trace_id="t-4")

        assert result is default
        mock_logger.warning.assert_called_once_with(
            "Parsed JSON is not a list", type="dict", trace_id="t-4"
        )

    @pytest.mark.parametrize("content", ["", "  "])
    def test_empty_content_raises(self, content: str) -> None:
        with pytest.raises(JSONParseError, match="Empty JSON content") as exc_info:
            parse_json_array_safe(content)

        assert exc_info.value.original_content == content

    def test_empty_content_returns_default(self) -> None:
        default: list[int] = []

        assert parse_json_array_safe("", default=default) is default

    def test_invalid_json_raises_with_cause(self) -> None:
        with pytest.raises(JSONParseError, match="Invalid JSON") as exc_info:
            parse_json_array_safe("[1, 2")

        assert exc_info.value.original_content == "[1, 2"
        assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)

    def test_invalid_json_returns_default_and_logs(self) -> None:
        with patch("app.utils.json_parser.logger") as mock_logger:
            result = parse_json_array_safe("[1, 2", default=[0], trace_id="t-5")

        assert result == [0]
        args, kwargs = mock_logger.error.call_args
        assert args == ("Failed to parse JSON array",)
        assert kwargs["trace_id"] == "t-5"


class TestExtractModelsFromResponse:
    def test_extracts_direct_array(self) -> None:
        content = '[{"name": "Model A"}, {"name": "Model B"}]'

        assert extract_models_from_response(content) == [
            {"name": "Model A"},
            {"name": "Model B"},
        ]

    def test_extracts_models_key(self) -> None:
        content = '```json\n{"models": [{"name": "Model A"}]}\n```'

        assert extract_models_from_response(content) == [{"name": "Model A"}]

    def test_extracts_data_key(self) -> None:
        assert extract_models_from_response('{"data": [{"name": "X"}]}') == [{"name": "X"}]

    @pytest.mark.parametrize("content", ["", "not json at all", '{"a": 1}', "42"])
    def test_unusable_content_returns_empty_list(self, content: str) -> None:
        assert extract_models_from_response(content) == []

    def test_parser_error_is_logged_and_swallowed(self) -> None:
        with (
            patch(
                "app.utils.json_parser.parse_json_array_safe",
                side_effect=JSONParseError("boom"),
            ) as mock_parse,
            patch("app.utils.json_parser.logger") as mock_logger,
        ):
            result = extract_models_from_response("[1]", trace_id="t-6")

        assert result == []
        mock_parse.assert_called_once_with("[1]", trace_id="t-6", default=[])
        mock_logger.error.assert_called_once_with(
            "Failed to extract models from response",
            content_preview="[1]",
            trace_id="t-6",
        )
