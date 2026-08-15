from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.types import String, TypeDecorator

# SQLite has no native arbitrary-precision decimal type, and SQLAlchemy's
# stock Numeric can silently degrade to REAL (float) on SQLite depending on
# driver behaviour. Storing as TEXT and parsing back via Decimal(text) is
# the only way to guarantee exact round-tripping (docs/data-model.md).


class Money(TypeDecorator):
    """EUR amounts. Always quantized to exactly 2 decimal places."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return str(quantized)

    def process_result_value(self, value, dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)


class Quantity(TypeDecorator):
    """Instrument quantities and native-currency prices. Up to 8 decimal
    places (BTC precision), stored exactly as given — never rounded."""

    impl = String
    cache_ok = True
    MAX_DECIMAL_PLACES = 8

    def process_bind_param(self, value, dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        exponent = value.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -self.MAX_DECIMAL_PLACES:
            raise ValueError(
                f"Quantity supports at most {self.MAX_DECIMAL_PLACES} "
                f"decimal places, got {value}"
            )
        return str(value)

    def process_result_value(self, value, dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(value)
