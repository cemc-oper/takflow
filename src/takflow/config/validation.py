"""Opt-in configuration loading with safe, structured diagnostics.

The historical loader keeps its exception and extra-field policies. These
entry points apply canonical top-level overrides before application validators,
and can request recursive unknown-field rejection with Pydantic >= 2.12.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Any, TypeVar

from pydantic import ValidationError
import yaml

from takflow.config.workflow import BaseWorkflowConfig


ConfigT = TypeVar("ConfigT", bound=BaseWorkflowConfig)


@dataclass(frozen=True)
class ConfigDiagnostic:
    """A reportable error containing no raw input or exception context."""

    code: str
    path: tuple[str | int, ...]
    reason: str
    stage: str = "config.validation"

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "path": list(self.path),
                "reason": self.reason, "stage": self.stage}


class ConfigValidationError(ValueError):
    """Safe configuration failure; adapters can render ``diagnostics``."""

    def __init__(self, diagnostics: tuple[ConfigDiagnostic, ...]):
        self.diagnostics = diagnostics
        super().__init__("\n".join(
            f"[{item.code}] {item.stage} {'.'.join(map(str, item.path)) or '$'}: {item.reason}"
            for item in diagnostics
        ))


_REASONS = {
    "config_date_invalid": ("CONFIG_DATE_INVALID", "must be a real calendar date in YYYYMMDD format"),
    "config_date_order": ("CONFIG_DATE_ORDER", "end_date must be on or after start_date"),
    "resource_positive": ("CONFIG_RESOURCE_POSITIVE", "must be a positive integer or None"),
    "extra_forbidden": ("CONFIG_UNKNOWN_FIELD", "unknown configuration field"),
    "missing": ("CONFIG_REQUIRED", "required configuration field is missing"),
    "literal_error": ("CONFIG_CHOICE", "value is not one of the declared choices"),
    "enum": ("CONFIG_CHOICE", "value is not one of the declared choices"),
    "union_tag_invalid": ("CONFIG_CHOICE", "unknown configuration variant"),
    "union_tag_not_found": ("CONFIG_REQUIRED", "configuration variant selector is missing"),
    "value_error": ("CONFIG_DOMAIN_RULE", "application configuration rule rejected this object"),
    "assertion_error": ("CONFIG_DOMAIN_RULE", "application configuration rule rejected this object"),
}


def validation_diagnostics(
    error: ValidationError, *, stage: str = "config.validation",
) -> tuple[ConfigDiagnostic, ...]:
    """Adapt Pydantic errors without copying inputs, ctx or arbitrary messages.

    Even a validator's message may contain credentials. Unrecognized/domain
    errors therefore use controlled reasons; the application's raw exception
    remains available only through its historical validation entry point.
    """
    diagnostics = []
    # Pydantic 2.0 has no include_input keyword. Select only type/loc below;
    # never copy its input value or original message into a diagnostic.
    for detail in error.errors(include_context=False, include_url=False):
        kind = detail["type"]
        if kind in _REASONS:
            code, reason = _REASONS[kind]
        elif kind.endswith(("_type", "_parsing")) or kind == "int_from_float":
            code, reason = "CONFIG_TYPE", "value has an invalid type or representation"
        elif kind in {"greater_than", "greater_than_equal", "less_than", "less_than_equal"}:
            code, reason = "CONFIG_RANGE", "value is outside the declared bounds"
        else:
            code, reason = "CONFIG_INVALID", "value does not satisfy the declared configuration rule"
        diagnostics.append(ConfigDiagnostic(code, tuple(detail["loc"]), reason, stage))
    return tuple(diagnostics)


def _fail(code: str, reason: str, stage: str, path: tuple[str | int, ...] = ()) -> None:
    raise ConfigValidationError((ConfigDiagnostic(code, path, reason, stage),)) from None


def apply_config_overrides(
    data: Mapping[str, Any],
    config_class: type[ConfigT] = BaseWorkflowConfig,
    *,
    overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy raw configuration and apply canonical top-level overrides.

    An override replaces the entire field, including a mapping-valued section;
    it is not a deep merge. Aliases for that field are removed first so they
    cannot defeat an explicit canonical override. Omitted keys and explicit
    None remain distinct for application validators and ``model_fields_set``.
    Neither input mapping is mutated. Model instances are not accepted as raw
    input because dumping them would lose their original explicit-field state.
    """
    if not isinstance(data, Mapping):
        _fail("CONFIG_ROOT_TYPE", "configuration must be a mapping", "config.validation")
    values = deepcopy(dict(data))
    if overrides is not None:
        if not isinstance(overrides, Mapping):
            _fail("CONFIG_OVERRIDES_TYPE", "overrides must be a mapping", "config.overrides")
        for name, value in overrides.items():
            field = config_class.model_fields.get(name)
            if field is None:
                _fail("CONFIG_UNKNOWN_FIELD", "override must name a canonical configuration field",
                      "config.overrides", (str(name),))
            alias = field.validation_alias or field.alias or name
            if not isinstance(alias, str):
                _fail("CONFIG_OVERRIDE_ALIAS", "overriding fields with alias paths or choices is unsupported",
                      "config.overrides", (name,))
            for key in {name, field.alias, field.validation_alias}:
                if isinstance(key, str):
                    values.pop(key, None)
            values[alias] = deepcopy(value)
    return values


def validate_config(
    data: Mapping[str, Any],
    config_class: type[ConfigT] = BaseWorkflowConfig,
    *,
    overrides: Mapping[str, Any] | None = None,
    strict_fields: bool = False,
) -> ConfigT:
    """Validate raw configuration after canonical whole-field overrides."""
    values = apply_config_overrides(data, config_class, overrides=overrides)
    if strict_fields and "extra" not in inspect.signature(config_class.model_validate).parameters:
        _fail("CONFIG_STRICT_UNAVAILABLE", "strict_fields requires takflow[strict-config] (Pydantic >= 2.12)",
              "config.validation")
    try:
        if strict_fields:
            return config_class.model_validate(values, extra="forbid")
        return config_class.model_validate(values)
    except ValidationError as error:
        raise ConfigValidationError(validation_diagnostics(error)) from None


def load_config_data(file_path: str | Path) -> Mapping[str, Any]:
    """Read a raw YAML mapping using the same safe diagnostics as validation."""
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        _fail("CONFIG_READ_ERROR", "configuration file could not be read as UTF-8", "config.read")
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        _fail("CONFIG_YAML_SYNTAX", "configuration is not valid YAML", "config.read")
    if not isinstance(data, Mapping):
        _fail("CONFIG_ROOT_TYPE", "configuration must be a mapping", "config.validation")
    return data


def load_validated_config(
    file_path: str | Path,
    config_class: type[ConfigT] = BaseWorkflowConfig,
    *,
    overrides: Mapping[str, Any] | None = None,
    strict_fields: bool = False,
) -> ConfigT:
    """Read UTF-8 YAML and validate without exposing input lines in errors."""
    data = load_config_data(file_path)
    return validate_config(data, config_class, overrides=overrides, strict_fields=strict_fields)


__all__ = ["ConfigDiagnostic", "ConfigValidationError", "validation_diagnostics",
           "validate_config", "load_validated_config", "load_config_data", "apply_config_overrides"]
