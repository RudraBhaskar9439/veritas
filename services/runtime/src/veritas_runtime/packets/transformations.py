from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

from veritas_runtime.packets.models import ClaimBlueprint, JsonScalar, SourceSnapshot


class TransformationError(ValueError):
    """A deterministic claim transformation could not be evaluated."""


Transformation = Callable[[ClaimBlueprint, SourceSnapshot], str]


class TransformationRegistry:
    def __init__(self, transformations: Mapping[str, Transformation] | None = None) -> None:
        self._transformations = dict(transformations or default_transformations())

    def render(
        self,
        claim: ClaimBlueprint,
        sources: Mapping[str, SourceSnapshot],
    ) -> str:
        try:
            source = sources[claim.source_ids[0]]
            transformation = self._transformations[claim.transformation]
        except KeyError as error:
            raise TransformationError(f"Unknown transformation input: {error.args[0]}") from error
        statement = transformation(claim, source).strip()
        if not statement:
            raise TransformationError("Transformation produced an empty statement")
        return statement


def default_transformations() -> Mapping[str, Transformation]:
    return {
        "identity_percent": _identity_percent,
        "compare_to_previous_quarter": _compare_to_previous,
        "churn_lte_target_5_percent": _threshold_statement,
        "recommend_if_churn_lte_5_percent": _threshold_statement,
        "identity_currency_millions": _identity_currency_millions,
        "identity_number": _identity_number,
        "identity_date": _identity_date,
    }


def _identity_percent(claim: ClaimBlueprint, source: SourceSnapshot) -> str:
    value = _decimal(source.value)
    return f"{_parameter(claim, 'prefix')}{_format_decimal(value * 100)}%."


def _compare_to_previous(claim: ClaimBlueprint, source: SourceSnapshot) -> str:
    current = _decimal(source.value)
    previous = _decimal(source.context.get("previous"))
    if current < previous:
        return _parameter(claim, "whenLower")
    if current > previous:
        return _parameter(claim, "whenHigher")
    return _parameter(claim, "whenEqual")


def _threshold_statement(claim: ClaimBlueprint, source: SourceSnapshot) -> str:
    current = _decimal(source.value)
    target = _decimal(claim.parameters.get("target"))
    return _parameter(claim, "whenTrue" if current <= target else "whenFalse")


def _identity_currency_millions(claim: ClaimBlueprint, source: SourceSnapshot) -> str:
    value = _format_decimal(_decimal(source.value))
    return f"{_parameter(claim, 'prefix')}${value}M."


def _identity_number(claim: ClaimBlueprint, source: SourceSnapshot) -> str:
    value = _format_decimal(_decimal(source.value))
    return f"{_parameter(claim, 'prefix')}{value}."


def _identity_date(claim: ClaimBlueprint, source: SourceSnapshot) -> str:
    try:
        resolved = date.fromisoformat(str(source.value))
    except ValueError as error:
        raise TransformationError("Date source must use ISO-8601") from error
    formatted = f"{resolved.strftime('%B')} {resolved.day}"
    return f"{_parameter(claim, 'prefix')}{formatted}."


def _parameter(claim: ClaimBlueprint, name: str) -> str:
    value: JsonScalar = claim.parameters.get(name)
    if not isinstance(value, str) or not value:
        raise TransformationError(
            f"Transformation {claim.transformation} requires string parameter {name}"
        )
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
