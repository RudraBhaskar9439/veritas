from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from veritas_runtime.packets.models import (
    ClaimBlueprint,
    ClaimRecord,
    JsonScalar,
    SourceSnapshot,
)


class TransformationError(ValueError):
    """A deterministic claim transformation could not be evaluated."""


@dataclass(frozen=True)
class TransformationInput:
    name: str
    version: str
    parameters: Mapping[str, JsonScalar]
    source_ids: tuple[str, ...]


Transformation = Callable[[TransformationInput, Mapping[str, SourceSnapshot]], str]


class TransformationRegistry:
    def __init__(self, transformations: Mapping[str, Transformation] | None = None) -> None:
        supplied = transformations or default_transformations()
        self._transformations = {
            key if "@" in key else f"{key}@1": transformation
            for key, transformation in supplied.items()
        }

    def render(
        self,
        claim: ClaimBlueprint | ClaimRecord,
        sources: Mapping[str, SourceSnapshot],
    ) -> str:
        spec = _input(claim)
        try:
            for source_id in spec.source_ids:
                sources[source_id]
            transformation = self._transformations[f"{spec.name}@{spec.version}"]
        except KeyError as error:
            raise TransformationError(f"Unknown transformation input: {error.args[0]}") from error
        statement = transformation(spec, sources).strip()
        if not statement:
            raise TransformationError("Transformation produced an empty statement")
        return statement


def default_transformations() -> Mapping[str, Transformation]:
    return {
        "identity_percent@1": _identity_percent,
        "compare_to_previous_quarter@1": _compare_to_previous,
        "churn_lte_target_5_percent@1": _threshold_statement,
        "recommend_if_churn_lte_5_percent@1": _threshold_statement,
        "identity_currency_millions@1": _identity_currency_millions,
        "identity_number@1": _identity_number,
        "identity_date@1": _identity_date,
    }


def _input(claim: ClaimBlueprint | ClaimRecord) -> TransformationInput:
    if isinstance(claim, ClaimBlueprint):
        return TransformationInput(
            name=claim.transformation,
            version=claim.transformation_version,
            parameters=claim.parameters,
            source_ids=claim.source_ids,
        )
    if claim.transformation is None:
        raise TransformationError(f"Claim {claim.claim_id} has no registered transformation")
    return TransformationInput(
        name=claim.transformation.name,
        version=claim.transformation.version,
        parameters=claim.transformation.parameters,
        source_ids=claim.source_ids,
    )


def _source(
    claim: TransformationInput,
    sources: Mapping[str, SourceSnapshot],
    index: int = 0,
) -> SourceSnapshot:
    try:
        return sources[claim.source_ids[index]]
    except IndexError as error:
        raise TransformationError(
            f"Transformation {claim.name} requires at least {index + 1} registered sources"
        ) from error


def _identity_percent(claim: TransformationInput, sources: Mapping[str, SourceSnapshot]) -> str:
    value = _decimal(_source(claim, sources).value)
    return f"{_parameter(claim, 'prefix')}{_format_decimal(value * 100)}%."


def _compare_to_previous(claim: TransformationInput, sources: Mapping[str, SourceSnapshot]) -> str:
    current = _decimal(_source(claim, sources).value)
    previous = _decimal(_source(claim, sources, 1).value)
    if current < previous:
        return _parameter(claim, "whenLower")
    if current > previous:
        return _parameter(claim, "whenHigher")
    return _parameter(claim, "whenEqual")


def _threshold_statement(claim: TransformationInput, sources: Mapping[str, SourceSnapshot]) -> str:
    current = _decimal(_source(claim, sources).value)
    target = _decimal(claim.parameters.get("target"))
    return _parameter(claim, "whenTrue" if current <= target else "whenFalse")


def _identity_currency_millions(
    claim: TransformationInput, sources: Mapping[str, SourceSnapshot]
) -> str:
    value = _format_decimal(_decimal(_source(claim, sources).value))
    return f"{_parameter(claim, 'prefix')}${value}M."


def _identity_number(claim: TransformationInput, sources: Mapping[str, SourceSnapshot]) -> str:
    value = _format_decimal(_decimal(_source(claim, sources).value))
    return f"{_parameter(claim, 'prefix')}{value}."


def _identity_date(claim: TransformationInput, sources: Mapping[str, SourceSnapshot]) -> str:
    try:
        resolved = date.fromisoformat(str(_source(claim, sources).value))
    except ValueError as error:
        raise TransformationError("Date source must use ISO-8601") from error
    formatted = f"{resolved.strftime('%B')} {resolved.day}"
    return f"{_parameter(claim, 'prefix')}{formatted}."


def _parameter(claim: TransformationInput, name: str) -> str:
    value: JsonScalar = claim.parameters.get(name)
    if not isinstance(value, str) or not value:
        raise TransformationError(f"Transformation {claim.name} requires string parameter {name}")
    return value


def _decimal(value: JsonScalar) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise TransformationError("Numeric source value is required")
    try:
        return Decimal(str(value))
    except InvalidOperation as error:
        raise TransformationError("Numeric source value is invalid") from error


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")
