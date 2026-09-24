"""
Robust JSON Parser.

Utilities for JSON parsing with robust error handling,
schema validation and structured logging.
"""

import json
import re
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class JSONParseError(Exception):
    """JSON parsing specific error."""

    def __init__(self, message: str, original_content: str | None = None):
        super().__init__(message)
        self.original_content = original_content


def _extract_json_from_markdown(content: str) -> str:
    """
    Extract JSON from markdown blocks or mixed text.

    OpenAI sometimes returns JSON inside ```json``` blocks.

    Args:
        content: String that may contain raw or markdown-wrapped JSON.

    Returns:
        String with JSON only.
    """
    # Remove markdown blocks ```json ... ```
    json_block_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    match = re.search(json_block_pattern, content)
    if match:
        return match.group(1).strip()

    # Try to find inline JSON (starts with { or [)
    content = content.strip()
    if content.startswith("{") or content.startswith("["):
        return content

    # Find first { or [ in text
    json_start = -1
    for i, char in enumerate(content):
        if char in "{[":
            json_start = i
            break

    if json_start >= 0:
        return content[json_start:]

    return content


def parse_json_safe(
    content: str,
    expected_keys: list[str] | None = None,
    trace_id: str | None = None,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Parse JSON safely with validation and logging.

    Tries to extract JSON from multiple formats (raw, markdown)
    and validates presence of expected keys.

    Args:
        content: String containing JSON.
        expected_keys: List of keys that must be present.
        trace_id: Trace ID for logging.
        default: Default value if parsing fails (None raises exception).

    Returns:
        Parsed dictionary.

    Raises:
        JSONParseError: If parsing fails and default is not provided.
    """
    if not content or not content.strip():
        if default is not None:
            logger.warning(
                "Empty JSON received, using default",
                trace_id=trace_id,
            )
            return default
        raise JSONParseError("Empty JSON content", original_content=content)

    # Extract JSON from possible wrappers
    cleaned = _extract_json_from_markdown(content)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse JSON",
            error=str(e),
            content_preview=content[:200] if content else None,
            trace_id=trace_id,
        )
        if default is not None:
            return default
        raise JSONParseError(
            f"Invalid JSON: {e}",
            original_content=content,
        ) from e

    # Ensure it is a dict
    if not isinstance(result, dict):
        logger.warning(
            "Parsed JSON is not a dictionary",
            type=type(result).__name__,
            trace_id=trace_id,
        )
        # If list, try to wrap
        if isinstance(result, list):
            result = {"items": result}
        elif default is not None:
            return default
        else:
            raise JSONParseError(
                f"JSON expected as object, got {type(result).__name__}",
                original_content=content,
            )

    # Validate expected keys
    if expected_keys:
        missing = [k for k in expected_keys if k not in result]
        if missing:
            logger.warning(
                "JSON missing expected keys",
                missing_keys=missing,
                available_keys=list(result.keys()),
                trace_id=trace_id,
            )

    return result


def parse_json_array_safe(
    content: str,
    trace_id: str | None = None,
    default: list[Any] | None = None,
) -> list[Any]:
    """
    Parse JSON array safely.

    Useful when expecting a list directly from the response.

    Args:
        content: String containing JSON array.
        trace_id: Trace ID for logging.
        default: Default value if parsing fails (None raises exception).

    Returns:
        Parsed list.

    Raises:
        JSONParseError: If parsing fails and default is not provided.
    """
    if not content or not content.strip():
        if default is not None:
            return default
        raise JSONParseError("Empty JSON content", original_content=content)

    cleaned = _extract_json_from_markdown(content)

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(
            "Failed to parse JSON array",
            error=str(e),
            content_preview=content[:200] if content else None,
            trace_id=trace_id,
        )
        if default is not None:
            return default
        raise JSONParseError(
            f"Invalid JSON: {e}",
            original_content=content,
        ) from e

    # If dict with items, extract
    if isinstance(result, dict):
        if "items" in result:
            result = result["items"]
        elif "models" in result:
            result = result["models"]
        elif "data" in result:
            result = result["data"]
        else:
            # Try first value that is a list
            for value in result.values():
                if isinstance(value, list):
                    result = value
                    break

    if not isinstance(result, list):
        logger.warning(
            "Parsed JSON is not a list",
            type=type(result).__name__,
            trace_id=trace_id,
        )
        if default is not None:
            return default
        raise JSONParseError(
            f"JSON expected as array, got {type(result).__name__}",
            original_content=content,
        )

    return result


def extract_models_from_response(
    content: str,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Extract list of models from OpenAI response.

    Handles multiple response formats:
    - Direct array: [{"name": ...}, ...]
    - Object with models: {"models": [...]}
    - Object with data: {"data": [...]}

    Args:
        content: OpenAI response.
        trace_id: Trace ID for logging.

    Returns:
        Extracted list of models.
    """
    try:
        result = parse_json_array_safe(content, trace_id=trace_id, default=[])
        return result
    except JSONParseError:
        logger.error(
            "Failed to extract models from response",
            content_preview=content[:200] if content else None,
            trace_id=trace_id,
        )
        return []
