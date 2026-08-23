"""Single dispatch point for "what is one unit / one holding of this
instrument worth as of this date" across the three position-bearing
valuation modes (MARKET, ANCHORED, MODELED). NOMINAL (cash) and
AMORTIZING_LIABILITY (loans) are account-type-driven special cases handled
by cash_service/loan_service directly, not through an Instrument — a LOAN
account's balance comes from its `loan` row, not from holding a quantity
of some instrument.
"""

import json
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.car_valuation import CarValuationConfig, car_residual_value
from app.house_valuation import house_value
from app.models import FxRate, HousePriceIndexPoint, Instrument, PricePoint, ValuationAnchor, ValuationMode


def _market_value(db: Session, instrument: Instrument, as_of: date) -> Decimal | None:
    """Value of one unit of `quantity` — one share's price in EUR, or (when
    `fine_weight_g` is set) one physical piece's EUR value. Callers
    multiply this by `quantity` for the total, so both cases keep the same
    contract."""
    price_point = (
        db.query(PricePoint)
        .filter(PricePoint.instrument_id == instrument.id, PricePoint.date <= as_of)
        .order_by(PricePoint.date.desc())
        .first()
    )
    if price_point is None:
        return None
    if instrument.currency == "EUR":
        fx = Decimal(1)
    else:
        fx_row = (
            db.query(FxRate)
            .filter(FxRate.currency == instrument.currency, FxRate.date <= as_of)
            .order_by(FxRate.date.desc())
            .first()
        )
        if fx_row is None:
            return None
        fx = fx_row.eur_rate
    spot_eur = price_point.close * fx
    if instrument.fine_weight_g is not None:
        # Physical metals (spec 3.2): the instrument is a physical unit,
        # not a spot-priced share. value = fine_weight_grams x
        # spot_eur_per_gram, where fine weight = quantity (pieces) x
        # fine_weight_g (grams per piece) — applied here per piece so the
        # x quantity multiplication callers already do still yields the
        # full holding's value. `price_point.close` must be sourced per
        # gram, in `instrument.currency`, for this to be correct — that is
        # not enforced here, only assumed once fine_weight_g is set.
        return instrument.fine_weight_g * spot_eur
    return spot_eur


def _anchored_value(db: Session, instrument: Instrument, as_of: date) -> Decimal | None:
    anchor = (
        db.query(ValuationAnchor)
        .filter(ValuationAnchor.instrument_id == instrument.id, ValuationAnchor.date <= as_of)
        .order_by(ValuationAnchor.date.desc())
        .first()
    )
    if anchor is None:
        return None
    config = json.loads(instrument.valuation_config_json or "{}")
    series_name = config.get("index_series")
    index_series: list[tuple[date, Decimal]] = []
    if series_name:
        index_series = [
            (row.date, row.index_value)
            for row in db.query(HousePriceIndexPoint)
            .filter(HousePriceIndexPoint.series == series_name)
            .order_by(HousePriceIndexPoint.date)
            .all()
        ]
    return house_value(anchor.value_eur, anchor.date, as_of, index_series)


def _modeled_value(instrument: Instrument, as_of: date) -> Decimal | None:
    config = json.loads(instrument.valuation_config_json or "{}")
    required = (
        "purchase_price_eur",
        "purchase_date",
        "first_registration",
        "mileage_at_purchase_km",
        "annual_mileage_estimate_km",
    )
    if not all(k in config for k in required):
        return None
    car_config = CarValuationConfig(
        purchase_price_eur=Decimal(config["purchase_price_eur"]),
        purchase_date=date.fromisoformat(config["purchase_date"]),
        first_registration=date.fromisoformat(config["first_registration"]),
        mileage_at_purchase_km=Decimal(str(config["mileage_at_purchase_km"])),
        annual_mileage_estimate_km=Decimal(str(config["annual_mileage_estimate_km"])),
        initial_drop=Decimal(str(config.get("initial_drop", "0.20"))),
        k=Decimal(str(config.get("k", "0.13"))),
        floor_pct=Decimal(str(config.get("floor_pct", "0.10"))),
    )
    return car_residual_value(car_config, as_of)


def current_instrument_value(
    db: Session, instrument_id: int, as_of: date
) -> Decimal | None:
    """Value of *one unit* for MARKET, or the *whole holding* for
    ANCHORED/MODELED (a house or car is never fractional — quantity is
    always 1 for these, unlike a MARKET instrument's per-share price)."""
    instrument = db.get(Instrument, instrument_id)
    if instrument is None:
        return None
    if instrument.valuation_mode == ValuationMode.MARKET:
        return _market_value(db, instrument, as_of)
    if instrument.valuation_mode == ValuationMode.ANCHORED:
        return _anchored_value(db, instrument, as_of)
    if instrument.valuation_mode == ValuationMode.MODELED:
        return _modeled_value(instrument, as_of)
    return None
