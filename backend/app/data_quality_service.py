"""Data quality panel (spec 4.6): "which valuation is how old, which
price is stale, which position has no cost basis — prevents silent trust
in outdated figures." A read-only aggregation over currently-open
positions; adds no new storage.
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app import kv_store
from app.ledger import compute_positions, txn_to_event
from app.models import (
    Account,
    AccountType,
    EtfComposition,
    Instrument,
    PricePoint,
    TransactionType,
    Txn,
    ValuationAnchor,
    ValuationMode,
)
from app.valuation_service import current_instrument_value

STALE_PRICE_DAYS = 7
# House/car appraisals are naturally infrequent (spec 3.3/3.4) — a much
# longer threshold than a tradeable instrument's price, so this only
# flags an anchor that's genuinely been left untouched for years.
STALE_VALUATION_DAYS = 730
# spec 6.6: "the data quality panel warns when the last successful backup
# is older than 48 hours."
STALE_BACKUP_HOURS = 48
# The offsite (NAS) leg is judged more leniently than the local backup on
# purpose (ADR 0015): a NAS reboot, a firmware update or a night of disk
# hibernation shouldn't cry wolf, but a leg that has genuinely stopped
# still surfaces within a few days rather than never.
STALE_OFFSITE_BACKUP_HOURS = 72
# Fund compositions have no automatic source, so they only refresh when
# somebody sits down with the factsheets. Index region weights drift on
# the order of a point a year, which makes a year the point where the
# breakdown is worth a look rather than the point where it's wrong.
STALE_COMPOSITION_DAYS = 365
# A cash balance has no market price to refresh it: past the last
# statement the snapshot engine simply carries the figure forward, so its
# only protection against silent drift is being told how old it is. Three
# months is roughly the point where a current account has moved enough
# that the number is worth re-reading off the bank.
STALE_CASH_STATEMENT_DAYS = 90
# Same files scripts/backup.sh writes and app.routers.health reads — a
# module-level path rather than importing health.py, so this stays a
# read-only aggregation with no dependency on another router.
_LAST_SUCCESS_FILE = Path("/backup-status/last_success")
_LAST_OFFSITE_FILE = Path("/backup-status/last_offsite_success")
# ADR 0009's named failure mode: price fetch and snapshot rebuild run
# in-process on a nightly cron (22:30/23:00 Europe/Berlin, scheduler.py),
# but until now nothing ever judged their kv_store.set() timestamps for
# staleness — a rebuild that silently stopped running produced no signal
# anywhere in the app, unlike the two backup markers below which already
# had issue kinds. 48h (same as the local backup threshold) tolerates one
# missed night before flagging; these are in-process jobs with no NAS/
# network dependency, so there's no reason to be as lenient as the
# offsite backup leg.
STALE_PRICE_FETCH_HOURS = 48
STALE_SNAPSHOT_HOURS = 48
_LAST_PRICE_FETCH_KEY = "last_price_fetch"
_LAST_SNAPSHOT_KEY = "last_snapshot"


@dataclass
class DataQualityIssue:
    kind: str
    detail: str
    # None for system-level issues (e.g. backup staleness) that aren't
    # about a specific instrument/account.
    instrument_id: int | None = None
    instrument_name: str | None = None
    account_id: int | None = None
    age_days: int | None = None


def _marker_issue(
    now: datetime,
    path: Path,
    threshold_hours: int,
    missing_kind: str,
    stale_kind: str,
    label: str,
) -> DataQualityIssue | None:
    """Age one of backup.sh's success markers into an issue, or None if it
    is recent enough. A marker that is absent, empty or unparseable counts
    as "never succeeded" rather than raising — the panel reporting on a
    failed backup is exactly the moment it must not itself fall over."""
    try:
        text = path.read_text().strip()
    except (FileNotFoundError, OSError):
        text = ""
    if not text:
        return DataQualityIssue(kind=missing_kind, detail=f"No successful {label} recorded yet")
    try:
        last = datetime.fromisoformat(text)
    except ValueError:
        return DataQualityIssue(kind=missing_kind, detail=f"No successful {label} recorded yet")
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age_hours = (now - last).total_seconds() / 3600
    if age_hours > threshold_hours:
        return DataQualityIssue(
            kind=stale_kind,
            detail=f"Last successful {label} is {int(age_hours)}h old",
            age_days=int(age_hours / 24),
        )
    return None


def _backup_issue(now: datetime) -> DataQualityIssue | None:
    return _marker_issue(
        now,
        _LAST_SUCCESS_FILE,
        STALE_BACKUP_HOURS,
        "missing_backup",
        "stale_backup",
        "backup",
    )


def _offsite_backup_issue(now: datetime) -> DataQualityIssue | None:
    return _marker_issue(
        now,
        _LAST_OFFSITE_FILE,
        STALE_OFFSITE_BACKUP_HOURS,
        "missing_offsite_backup",
        "stale_offsite_backup",
        "offsite backup",
    )


def _kv_job_issue(
    db: Session,
    now: datetime,
    key: str,
    threshold_hours: int,
    missing_kind: str,
    stale_kind: str,
    label: str,
) -> DataQualityIssue | None:
    """Same aging logic as _marker_issue, but for a scheduler.py job
    timestamp recorded via kv_store.set() instead of a backup.sh file
    marker. A missing/unparseable value counts as "never run" — same
    fail-open-to-a-visible-issue posture as the backup markers."""
    raw = kv_store.get(db, key)
    if not raw:
        return DataQualityIssue(kind=missing_kind, detail=f"No successful {label} recorded yet")
    try:
        last = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return DataQualityIssue(kind=missing_kind, detail=f"No successful {label} recorded yet")
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age_hours = (now - last).total_seconds() / 3600
    if age_hours > threshold_hours:
        return DataQualityIssue(
            kind=stale_kind,
            detail=f"Last successful {label} is {int(age_hours)}h old",
            age_days=int(age_hours / 24),
        )
    return None


def _price_fetch_job_issue(db: Session, now: datetime) -> DataQualityIssue | None:
    return _kv_job_issue(
        db,
        now,
        _LAST_PRICE_FETCH_KEY,
        STALE_PRICE_FETCH_HOURS,
        "missing_price_fetch_job",
        "stale_price_fetch_job",
        "price fetch run",
    )


def _snapshot_job_issue(db: Session, now: datetime) -> DataQualityIssue | None:
    return _kv_job_issue(
        db,
        now,
        _LAST_SNAPSHOT_KEY,
        STALE_SNAPSHOT_HOURS,
        "missing_snapshot_job",
        "stale_snapshot_job",
        "snapshot rebuild",
    )


def check_data_quality(db: Session, as_of: date | None = None) -> list[DataQualityIssue]:
    as_of = as_of or date.today()
    issues: list[DataQualityIssue] = []

    now = datetime.now(timezone.utc)
    for check in (_backup_issue, _offsite_backup_issue):
        issue = check(now)
        if issue is not None:
            issues.append(issue)

    # Independent of the two backup markers above (ADR 0015's independence
    # requirement is about the two backup legs specifically) — these two
    # are a different failure mode (an in-process scheduled job, not an
    # external script) and are additive, never a substitute for either.
    for job_check in (_price_fetch_job_issue, _snapshot_job_issue):
        issue = job_check(db, now)
        if issue is not None:
            issues.append(issue)

    txns = db.query(Txn).filter(Txn.voided_at.is_(None), Txn.instrument_id.isnot(None)).all()
    events = [txn_to_event(t) for t in txns]
    positions = compute_positions(events)

    instruments = {i.id: i for i in db.query(Instrument).all()}

    for (account_id, instrument_id), pos in positions.items():
        if pos.quantity == 0:
            continue
        instrument = instruments.get(instrument_id)
        if instrument is None:
            continue

        if pos.cost_basis_eur == 0:
            issues.append(
                DataQualityIssue(
                    kind="no_cost_basis",
                    instrument_id=instrument_id,
                    instrument_name=instrument.name,
                    account_id=account_id,
                    detail="Open position with zero recorded cost basis",
                )
            )

        if instrument.valuation_mode == ValuationMode.MARKET:
            latest_price = (
                db.query(PricePoint)
                .filter(PricePoint.instrument_id == instrument_id)
                .order_by(PricePoint.date.desc())
                .first()
            )
            if latest_price is None:
                issues.append(
                    DataQualityIssue(
                        kind="missing_price",
                        instrument_id=instrument_id,
                        instrument_name=instrument.name,
                        account_id=account_id,
                        detail="No price data at all",
                    )
                )
            else:
                age = (as_of - latest_price.date).days
                if age > STALE_PRICE_DAYS:
                    issues.append(
                        DataQualityIssue(
                            kind="stale_price",
                            instrument_id=instrument_id,
                            instrument_name=instrument.name,
                            account_id=account_id,
                            detail=f"Last price is {age} days old",
                            age_days=age,
                        )
                    )

        elif instrument.valuation_mode in (ValuationMode.ANCHORED, ValuationMode.MODELED):
            if current_instrument_value(db, instrument_id, as_of) is None:
                issues.append(
                    DataQualityIssue(
                        kind="missing_valuation",
                        instrument_id=instrument_id,
                        instrument_name=instrument.name,
                        account_id=account_id,
                        detail="No usable valuation (missing anchor or incomplete config)",
                    )
                )
            elif instrument.valuation_mode == ValuationMode.ANCHORED:
                # MODELED (car) is a continuous formula, not a point-in-
                # time anchor — only ANCHORED (house) has a genuine
                # "how old is the last appraisal" question.
                latest_anchor = (
                    db.query(ValuationAnchor)
                    .filter(ValuationAnchor.instrument_id == instrument_id)
                    .order_by(ValuationAnchor.date.desc())
                    .first()
                )
                age = (as_of - latest_anchor.date).days
                if age > STALE_VALUATION_DAYS:
                    issues.append(
                        DataQualityIssue(
                            kind="stale_valuation",
                            instrument_id=instrument_id,
                            instrument_name=instrument.name,
                            account_id=account_id,
                            detail=f"Last valuation is {age} days old",
                            age_days=age,
                        )
                    )

    issues.extend(_cash_statement_issues(db, as_of))
    issues.extend(_composition_issues(db, positions, instruments, as_of))
    return issues


def _cash_statement_issues(db: Session, as_of: date) -> list[DataQualityIssue]:
    """Flags cash accounts whose last balance statement has gone stale.

    Unlike a position, a cash account carries no instrument and no price,
    so nothing else in this panel would ever mention it — and the
    snapshot engine keeps reporting the last known balance indefinitely.
    An account that never had a statement at all is not flagged: it holds
    nothing and contributes nothing, which is not a data-quality problem.
    """
    issues: list[DataQualityIssue] = []
    accounts = (
        db.query(Account)
        .filter(Account.type == AccountType.CASH, Account.archived.is_(False))
        .all()
    )
    for account in accounts:
        latest = (
            db.query(Txn)
            .filter(
                Txn.account_id == account.id,
                Txn.type == TransactionType.BALANCE_STATEMENT,
                Txn.voided_at.is_(None),
            )
            .order_by(Txn.date.desc())
            .first()
        )
        if latest is None:
            continue
        age = (as_of - latest.date).days
        if age > STALE_CASH_STATEMENT_DAYS:
            issues.append(
                DataQualityIssue(
                    kind="stale_cash_statement",
                    account_id=account.id,
                    detail=(
                        f"{account.name}: last balance statement is {age} days old"
                    ),
                    age_days=age,
                )
            )
    return issues


def _composition_issues(db, positions, instruments, as_of: date) -> list[DataQualityIssue]:
    """Flags look-through breakdowns that are stale or of unknown age.

    Only for instruments actually held and actually carrying a breakdown:
    a directly-held share has none by design (it falls back to its own
    region/sector fields), so its absence is not a defect. A *missing*
    breakdown isn't reported here either — it already shows up in the
    look-through itself as an "Unknown" slice, which is louder than a
    line in a panel.
    """
    held = {
        instrument_id
        for (_, instrument_id), pos in positions.items()
        if pos.quantity != 0
    }
    if not held:
        return []

    newest: dict[tuple[int, str], datetime | None] = {}
    rows = (
        db.query(EtfComposition)
        .filter(EtfComposition.instrument_id.in_(held))
        .all()
    )
    for row in rows:
        key = (row.instrument_id, row.dimension)
        if key not in newest:
            newest[key] = row.updated_at
        elif newest[key] is not None and (
            row.updated_at is None or row.updated_at < newest[key]
        ):
            # The oldest row in a pair sets its age — the PUT writes them
            # together, so a straggler means a partial or hand-edited write.
            newest[key] = row.updated_at

    issues: list[DataQualityIssue] = []
    for (instrument_id, dimension), updated_at in sorted(newest.items()):
        instrument = instruments.get(instrument_id)
        if instrument is None:
            continue
        if updated_at is None:
            issues.append(
                DataQualityIssue(
                    kind="composition_age_unknown",
                    instrument_id=instrument_id,
                    instrument_name=instrument.name,
                    detail=f"{dimension} breakdown has no recorded entry date",
                )
            )
            continue
        age = (as_of - updated_at.date()).days
        if age > STALE_COMPOSITION_DAYS:
            issues.append(
                DataQualityIssue(
                    kind="stale_composition",
                    instrument_id=instrument_id,
                    instrument_name=instrument.name,
                    detail=f"{dimension} breakdown is {age} days old",
                    age_days=age,
                )
            )
    return issues
