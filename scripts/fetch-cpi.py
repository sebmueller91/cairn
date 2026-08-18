#!/usr/bin/env python3
"""Fuellt cpi_index_point aus dem ECB Data Portal.

Hintergrund: routers/cpi.py sieht Handeingabe vor, weil Destatis GENESIS
eine Registrierung braucht, die nur der Nutzer selbst abschliessen kann.
Die EZB veroeffentlicht den harmonisierten Verbraucherpreisindex fuer
Deutschland (HICP) dagegen ohne Schluessel - dieselbe Quelle, aus der auch
die Wechselkurse kommen. Das ist nicht exakt der nationale VPI (andere
Gewichte, Wohneigentum wird anders behandelt), fuer eine reale
Vermoegenskurve ist der Unterschied aber belanglos.

    python3 scripts/fetch-cpi.py [--dry-run] [--start 2018-01]

Einmal im Jahr erneut laufen lassen; vorhandene Monate werden aktualisiert.
"""
import argparse
import csv
import io
import json
import os
import pathlib
import ssl
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("CAIRN_API_URL", "https://raspberrypi5")
CTX = ssl._create_unverified_context()
SERIES = "ICP/M.DE.N.000000.4.INX"
ECB = "https://data-api.ecb.europa.eu/service/data"


def token() -> str:
    t = os.environ.get("CAIRN_API_TOKEN")
    if t:
        return t.strip()
    path = pathlib.Path.home() / ".cairn-token"
    if path.exists():
        return path.read_text().strip()
    sys.exit("kein Token: CAIRN_API_TOKEN setzen oder ~/.cairn-token anlegen")


def fetch(start: str) -> list[tuple[str, str]]:
    url = f"{ECB}/{SERIES}?format=csvdata&detail=dataonly&startPeriod={start}"
    req = urllib.request.Request(url, headers={"User-Agent": "cairn/1.0"})
    with urllib.request.urlopen(req, context=CTX, timeout=120) as r:
        rows = list(csv.DictReader(io.StringIO(r.read().decode())))
    # TIME_PERIOD ist YYYY-MM; der erste des Monats ist der Stichtag, ab dem
    # der Wert gilt - deflate_series sucht per carry-forward rueckwaerts.
    return [(f"{row['TIME_PERIOD']}-01", row["OBS_VALUE"]) for row in rows if row["OBS_VALUE"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--start", default="2018-01")
    args = ap.parse_args()

    points = fetch(args.start)
    if not points:
        sys.exit("keine Datenpunkte erhalten")
    print(f"{len(points)} Monatswerte: {points[0][0]} ({points[0][1]}) "
          f".. {points[-1][0]} ({points[-1][1]})")
    if args.dry_run:
        print("Probelauf, nichts geschrieben")
        return

    tok = token()
    written = 0
    for day, value in points:
        req = urllib.request.Request(
            BASE + "/api/cpi",
            data=json.dumps({"date": day, "index_value": value}).encode(),
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, context=CTX, timeout=60).read()
            written += 1
        except urllib.error.HTTPError as e:
            sys.exit(f"POST /api/cpi {day} -> {e.code} {e.read().decode()[:300]}")
    print(f"{written} Punkte geschrieben")


if __name__ == "__main__":
    main()
