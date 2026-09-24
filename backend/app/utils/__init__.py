"""Utils module - Utility functions and helpers."""

from app.utils.json_parser import (
    JSONParseError,
    extract_models_from_response,
    parse_json_array_safe,
    parse_json_safe,
)
from app.utils.response_formatter import (
    dict_to_camel_case,
    dict_to_snake_case,
    format_extraction_response,
    format_model_extraction_response,
    format_section_extraction_response,
    to_camel_case,
    to_snake_case,
)

__all__ = [
    # JSON Parser
    "JSONParseError",
    "parse_json_safe",
    "parse_json_array_safe",
    "extract_models_from_response",
    # Response Formatter
    "to_camel_case",
    "to_snake_case",
    "dict_to_camel_case",
    "dict_to_snake_case",
    "format_extraction_response",
    "format_model_extraction_response",
    "format_section_extraction_response",
]
