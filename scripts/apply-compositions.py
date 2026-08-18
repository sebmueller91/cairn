#!/usr/bin/env python3
"""Spielt docs/etf-compositions.json in die laufende Instanz ein.

Die JSON-Datei ist die Wahrheitsquelle, nicht die Datenbank: Factsheet-
Zahlen dort korrigieren und dieses Skript erneut laufen lassen. Der
PUT-Endpunkt ersetzt die Aufteilung je (Instrument, Dimension)
vollstaendig, das Skript ist also idempotent.

    CAIRN_API_TOKEN=... python3 scripts/apply-compositions.py [--dry-run]

Ohne CAIRN_API_TOKEN wird ~/.cairn-token gelesen.
"""
import argparse
import json
import os
import pathlib
import ssl
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "etf-compositions.json"
BASE = os.environ.get("CAIRN_API_URL", "https://raspberrypi5")
# Die Instanz laeuft mit einem mkcert-Zertifikat im LAN; die Pruefung
# schlaegt je nach Trust-Store fehl und der Host ist ohnehin unser eigener.
CTX = ssl._create_unverified_context()


def token() -> str:
    t = os.environ.get("CAIRN_API_TOKEN")
    if t:
        return t.strip()
    path = pathlib.Path.home() / ".cairn-token"
    if path.exists():
        return path.read_text().strip()
    sys.exit("kein Token: CAIRN_API_TOKEN setzen oder ~/.cairn-token anlegen")


TOKEN = token()


def call(method: str, path: str, payload=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=120) as r:
            body = r.read().decode()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> {e.code} {e.read().decode()[:400]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="nur zeigen, was gesetzt wuerde")
    args = ap.parse_args()

    data = json.loads(DATA.read_text())
    instruments = call("GET", "/api/instruments")
    by_ticker = {i["ticker"]: i for i in instruments if i.get("ticker")}

    print(f"{'Ticker':10}{'Instrument':40}{'Dimension':10}{'Kategorien':>11}{'Summe':>8}")
    print("-" * 80)
    missing = []
    for ticker, spec in data["compositions"].items():
        inst = by_ticker.get(ticker)
        if inst is None:
            missing.append(ticker)
            continue
        for dimension in ("region", "sector"):
            breakdown = spec.get(dimension)
            if not breakdown:
                continue
            total = sum(breakdown.values())
            print(f"{ticker:10}{inst['name'][:38]:40}{dimension:10}"
                  f"{len(breakdown):>11}{total:>8.1f}")
            if abs(total - 100) > 1.0:
                sys.exit(f"  {ticker}/{dimension} summiert auf {total}, nicht ~100")
            if not args.dry_run:
                call("PUT", f"/api/instruments/{inst['id']}/composition",
                     {"dimension": dimension,
                      "breakdown": {k: str(v) for k, v in breakdown.items()}})

    print()
    for ticker, spec in data["direct_holdings"].items():
        if ticker.startswith("_"):
            continue
        inst = by_ticker.get(ticker)
        if inst is None:
            missing.append(ticker)
            continue
        print(f"{ticker:10}{inst['name'][:38]:40}{'direkt':10}"
              f"{spec['region']:>18} / {spec['sector']}")
        if not args.dry_run:
            call("PATCH", f"/api/instruments/{inst['id']}",
                 {"region": spec["region"], "sector": spec["sector"]})

    # Fonds oder Einzelwert als Tag am Instrument. Die Unterscheidung steht
    # ohnehin schon in dieser Datei - `compositions` sind Fonds, weil nur ein
    # Fonds eine Durchsicht hat, `direct_holdings` sind Einzelwerte. Sie am
    # Namen zu erraten ("...UCITS ETF") waere ein stiller Fehler, sobald ein
    # Fonds mal anders heisst.
    kinds = {t: "etf" for t in data["compositions"] if not t.startswith("_")}
    kinds |= {t: "direct" for t in data["direct_holdings"] if not t.startswith("_")}
    kinds |= {t: k for t, k in (data.get("kinds") or {}).items() if not t.startswith("_")}
    print()
    tagged = 0
    for ticker, kind in sorted(kinds.items()):
        inst = by_ticker.get(ticker)
        if inst is None:
            continue
        tags = sorted({*(t for t in inst["tags"] if t not in ("etf", "direct")), kind})
        if tags != sorted(inst["tags"]):
            tagged += 1
            if not args.dry_run:
                call("PATCH", f"/api/instruments/{inst['id']}", {"tags": tags})
    print(f"{'tag':10}{'Fonds/Einzelwert':40}{len(kinds):>11} zugeordnet, {tagged} geaendert")

    print()
    for dimension, spec in (data.get("benchmarks") or {}).items():
        if dimension.startswith("_"):
            continue
        total = sum(spec["breakdown"].values())
        print(f"{'benchmark':10}{spec['label'][:38]:40}{dimension:10}"
              f"{len(spec['breakdown']):>11}{total:>8.1f}")
        if abs(total - 100) > 1.0:
            sys.exit(f"  benchmark {dimension} summiert auf {total}, nicht ~100")
        if not args.dry_run:
            call("PUT", "/api/look-through/benchmark", {
                "dimension": dimension, "label": spec["label"],
                "breakdown": {k: str(v) for k, v in spec["breakdown"].items()},
            })

    if missing:
        print(f"\nnicht gefunden (Ticker stimmt nicht mit einem Instrument ueberein): {missing}")
    print("\nProbelauf, nichts geschrieben" if args.dry_run else "\ngeschrieben")


if __name__ == "__main__":
    main()
