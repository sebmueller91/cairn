"""Real (inflation-adjusted) wealth curve (spec 4.6): "the wealth curve
additionally adjusted for inflation (German CPI, annual maintenance is
enough)."
"""

from datetime import date
from decimal import Decimal


def deflate_series(
    values: list[tuple[date, Decimal]], cpi_points: list[tuple[date, Decimal]]
) -> list[tuple[date, Decimal]]:
    """Real value expressed in *today's* purchasing power:
    nominal(t) * CPI(latest known) / CPI(t), via carry-forward lookups
    against the (typically annual) CPI series. Points before the first
    known CPI value are returned unadjusted (nothing to deflate against
    yet) rather than dropped, so the curve stays the same length."""
    if not cpi_points:
        return values
    cpi_sorted = sorted(cpi_points, key=lambda p: p[0])
    latest_cpi = cpi_sorted[-1][1]

    out: list[tuple[date, Decimal]] = []
    idx = -1
    current_cpi: Decimal | None = None
    for d, v in values:
        while idx + 1 < len(cpi_sorted) and cpi_sorted[idx + 1][0] <= d:
            idx += 1
            current_cpi = cpi_sorted[idx][1]
        if current_cpi is None or current_cpi == 0:
            out.append((d, v))
        else:
            out.append((d, v * latest_cpi / current_cpi))
    return out
