"""Import holidays into building_calendar + load customer closure CSVs.

ENG-1d deliverable: populates the building_calendar table from two sources:
  1. Public holiday API (via the swappable HolidayProvider interface)
  2. Customer-uploaded closure CSV files

Usage:
    # Import public holidays for a building
    python scripts/migrations/import_holidays.py holidays \\
        --tenant-id <uuid> --building-id <uuid> \\
        --country-code IN --year 2026

    # Load customer-declared closures from CSV
    python scripts/migrations/import_holidays.py closures \\
        --tenant-id <uuid> --building-id <uuid> \\
        --csv-path /path/to/closures.csv

Closure CSV format:
    date,description
    2026-12-25,Annual shutdown
    2026-01-26,Republic Day closure

Weekend detection is automatic: any date falling on a Saturday or Sunday
that isn't already marked as a holiday or declared_closure is inserted
as day_type='weekend'. All other dates are 'business_day'.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import os
import sys
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.calendar.holiday_provider import (
    HolidayProvider,
    NagerDateHolidayProvider,
)


def _get_engine() -> sa.Engine:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://carbonsense:changeme@localhost:5432/carbonsense",
    )
    return create_engine(url)


def _upsert_calendar_entry(
    conn: sa.Connection,
    tenant_id: UUID,
    building_id: UUID,
    date: datetime.date,
    day_type: str,
    source: str,
) -> None:
    conn.execute(
        text("""
            INSERT INTO building_calendar (tenant_id, building_id, date, day_type, source)
            VALUES (:tenant_id, :building_id, :date, :day_type, :source)
            ON CONFLICT (tenant_id, building_id, date)
            DO UPDATE SET day_type = EXCLUDED.day_type, source = EXCLUDED.source
        """),
        {
            "tenant_id": str(tenant_id),
            "building_id": str(building_id),
            "date": date,
            "day_type": day_type,
            "source": source,
        },
    )


def import_holidays(
    tenant_id: UUID,
    building_id: UUID,
    country_code: str,
    year: int,
    provider: HolidayProvider | None = None,
) -> int:
    """Import public holidays from the configured provider."""
    if provider is None:
        provider = NagerDateHolidayProvider()

    holidays = provider.fetch_holidays(country_code, year)
    engine = _get_engine()
    count = 0

    with engine.begin() as conn:
        for holiday in holidays:
            _upsert_calendar_entry(
                conn,
                tenant_id,
                building_id,
                holiday.date,
                "holiday",
                f"holiday_api:{country_code}:{holiday.name}",
            )
            count += 1

    return count


def import_closures(
    tenant_id: UUID,
    building_id: UUID,
    csv_path: str,
) -> int:
    """Import customer-declared closures from a CSV file."""
    engine = _get_engine()
    count = 0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        with engine.begin() as conn:
            for row in reader:
                date = datetime.date.fromisoformat(row["date"].strip())
                description = row.get("description", "").strip()
                _upsert_calendar_entry(
                    conn,
                    tenant_id,
                    building_id,
                    date,
                    "declared_closure",
                    f"customer_upload:{description}" if description else "customer_upload",
                )
                count += 1

    return count


def backfill_weekends(
    tenant_id: UUID,
    building_id: UUID,
    year: int,
) -> int:
    """Fill in weekend entries for dates not already in the calendar."""
    engine = _get_engine()
    count = 0
    start = datetime.date(year, 1, 1)
    end = datetime.date(year, 12, 31)

    with engine.begin() as conn:
        existing = conn.execute(
            text("""
                SELECT date FROM building_calendar
                WHERE tenant_id = :tenant_id
                  AND building_id = :building_id
                  AND date >= :start AND date <= :end
            """),
            {
                "tenant_id": str(tenant_id),
                "building_id": str(building_id),
                "start": start,
                "end": end,
            },
        )
        existing_dates = {row[0] for row in existing}

        current = start
        while current <= end:
            if current not in existing_dates and current.weekday() >= 5:
                _upsert_calendar_entry(
                    conn, tenant_id, building_id, current, "weekend", "auto:weekday_check"
                )
                count += 1
            current += datetime.timedelta(days=1)

    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import holidays and closures into building_calendar"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    hol = sub.add_parser("holidays", help="Import public holidays from API")
    hol.add_argument("--tenant-id", type=UUID, required=True)
    hol.add_argument("--building-id", type=UUID, required=True)
    hol.add_argument("--country-code", required=True)
    hol.add_argument("--year", type=int, required=True)
    hol.add_argument(
        "--backfill-weekends",
        action="store_true",
        help="Also backfill weekend entries for the year",
    )

    clo = sub.add_parser("closures", help="Import customer-declared closures from CSV")
    clo.add_argument("--tenant-id", type=UUID, required=True)
    clo.add_argument("--building-id", type=UUID, required=True)
    clo.add_argument("--csv-path", required=True)

    args = parser.parse_args()

    if args.command == "holidays":
        count = import_holidays(args.tenant_id, args.building_id, args.country_code, args.year)
        print(f"Imported {count} holidays.")  # noqa: T201
        if args.backfill_weekends:
            wcount = backfill_weekends(args.tenant_id, args.building_id, args.year)
            print(f"Backfilled {wcount} weekend entries.")  # noqa: T201

    elif args.command == "closures":
        count = import_closures(args.tenant_id, args.building_id, args.csv_path)
        print(f"Imported {count} closure entries.")  # noqa: T201


if __name__ == "__main__":
    main()
