"""
Response Formatter.

Utilitários para formatação de respostas da API,
incluindo conversão entre snake_case e camelCase.
"""

import re
from typing import Any


def to_camel_case(snake_str: str) -> str:
    """
    Converte string de snake_case para camelCase.

    Args:
        snake_str: String em snake_case.

    Returns:
        String em camelCase.

    Exemplo:
        >>> to_camel_case("entity_type_id")
        "entityTypeId"
    """
    components = snake_str.split("_")
    return components[0] + "".join(x.title() for x in components[1:])


def to_snake_case(camel_str: str) -> str:
    """
    Converte string de camelCase para snake_case.

    Args:
        camel_str: String em camelCase.

    Returns:
        String em snake_case.

    Exemplo:
        >>> to_snake_case("entityTypeId")
        "entity_type_id"
    """
    return re.sub(r"(?<!^)(?=[A-Z])", "_", camel_str).lower()


def dict_to_camel_case(data: dict[str, Any]) -> dict[str, Any]:
    """
    Converte chaves de dict de snake_case para camelCase.

    Processa recursivamente dicts e listas aninhados.

    Args:
        data: Dicionário com chaves em snake_case.

    Returns:
        Dicionário com chaves em camelCase.
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        camel_key = to_camel_case(key)
        if isinstance(value, dict):
            result[camel_key] = dict_to_camel_case(value)
        elif isinstance(value, list):
            result[camel_key] = [
                dict_to_camel_case(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            result[camel_key] = value
    return result


def dict_to_snake_case(data: dict[str, Any]) -> dict[str, Any]:
    """
    Converte chaves de dict de camelCase para snake_case.

    Processa recursivamente dicts e listas aninhados.

    Args:
        data: Dicionário com chaves em camelCase.

    Returns:
        Dicionário com chaves em snake_case.
    """
    result: dict[str, Any] = {}
    for key, value in data.items():
        snake_key = to_snake_case(key)
        if isinstance(value, dict):
            result[snake_key] = dict_to_snake_case(value)
        elif isinstance(value, list):
            result[snake_key] = [
                dict_to_snake_case(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            result[snake_key] = value
    return result


def format_extraction_response(
    created_count: int,
    suggestions: list[dict[str, Any]] | None = None,
    models: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """
    Formata resposta padrão de extração.

    Cria uma resposta consistente para endpoints de extração
    com conversão automática para camelCase.

    Args:
        created_count: Número de itens criados.
        suggestions: Lista de sugestões criadas.
        models: Lista de modelos extraídos.
        error: Mensagem de erro, se houver.

    Returns:
        Resposta formatada em camelCase.
    """
    response: dict[str, Any] = {
        "created_count": created_count,
    }

    if suggestions is not None:
        response["suggestions"] = [
            dict_to_camel_case(s) if isinstance(s, dict) else s for s in suggestions
        ]

    if models is not None:
        response["models"] = [dict_to_camel_case(m) if isinstance(m, dict) else m for m in models]

    if error is not None:
        response["error"] = error

    return dict_to_camel_case(response)


def format_model_extraction_response(
    models_count: int,
    models: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Formata resposta de extração de modelos.

    Args:
        models_count: Número de modelos extraídos.
        models: Lista de modelos.

    Returns:
        Resposta formatada.
    """
    return {
        "modelsCount": models_count,
        "models": [dict_to_camel_case(m) if isinstance(m, dict) else m for m in models],
    }


def format_section_extraction_response(
    created_count: int,
    suggestions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Formata resposta de extração de seções.

    Args:
        created_count: Número de sugestões criadas.
        suggestions: Lista de sugestões.

    Returns:
        Resposta formatada.
    """
    return {
        "createdCount": created_count,
        "suggestions": [dict_to_camel_case(s) if isinstance(s, dict) else s for s in suggestions],
    }
