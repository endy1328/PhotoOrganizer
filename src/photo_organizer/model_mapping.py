"""Validate and resolve output aliases without changing camera metadata."""
from __future__ import annotations

import re
from collections.abc import Iterable

from .fallback import canonical_model_key, sanitize_model_name


def normalize_model_mapping_scope(value: object) -> str:
    return value if value in ("filename_and_folders", "filename_only") else "filename_and_folders"


def _component(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}을 입력해주세요.")
    if re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', value):
        raise ValueError(f"{label}에 파일명으로 사용할 수 없는 문자가 있습니다.")
    value = value.strip()
    if value in (".", "..") or value.endswith("."):
        raise ValueError(f"{label}은 점으로 끝날 수 없습니다.")
    if re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", value.split(".")[0].rstrip(), re.IGNORECASE):
        raise ValueError(f"{label}에 Windows 예약 이름을 사용할 수 없습니다.")
    if len(value.encode("utf-16-le")) // 2 > 180:
        raise ValueError(f"{label}은 180자 이내로 입력해주세요.")
    return value


def _source_key(source: str) -> str:
    if source.casefold() == "unknown":
        return "__unknown__"
    key = canonical_model_key(source)
    if not key:
        raise ValueError("원본 모델명은 미리보기에 표시된 모델명으로 입력해주세요.")
    return key


def validate_model_mapping_rows(rows: Iterable[tuple[str, str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    seen = set()
    for source, target in rows:
        if source == "" and target == "":
            continue  # An unused blank editor row is not a mapping.
        source = _component(source, "원본 모델명")
        target = _component(target, "사용할 이름").replace(" ", "_")
        key = _source_key(source)
        if key in seen:
            raise ValueError(f"원본 모델명이 중복되었습니다: {source}")
        seen.add(key)
        result[source] = target
    return result


def validate_model_mappings(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("모델명 매핑은 원본 모델명과 사용할 이름의 목록이어야 합니다.")
    if any(source == "" or alias == "" for source, alias in value.items()):
        raise ValueError("모델명 매핑의 원본 모델명과 사용할 이름은 비울 수 없습니다.")
    return validate_model_mapping_rows(value.items())


def normalize_loaded_model_mappings(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    seen = set()
    for source, target in value.items():
        try:
            valid = validate_model_mapping_rows([(source, target)])
            if not valid:
                continue
            source, target = next(iter(valid.items()))
            key = _source_key(source)
            if key not in seen:
                result[source] = target
                seen.add(key)
        except (ValueError, UnicodeError):
            continue
    return result


def resolve_output_model_name(original: str, mappings: dict[str, str]) -> str:
    sanitized = sanitize_model_name(original)
    try:
        key = _source_key(sanitized)
    except ValueError:
        return sanitized
    for source, alias in mappings.items():
        if _source_key(source) == key:
            return alias
    return sanitized


def model_mapping_signature(mappings: dict[str, str], scope: str) -> tuple:
    return (normalize_model_mapping_scope(scope),
            tuple(sorted((_source_key(source), alias) for source, alias in validate_model_mappings(mappings).items())))
