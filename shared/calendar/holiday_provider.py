"""Swappable holiday provider interface for building_calendar population.

Per DATA_AND_MODEL_STRATEGY §1 source-agnostic stance and TRD v2.0 §3.3:
the holiday-API provider is a swappable interface so the vendor can be
changed without touching detection logic.

Implementations:
    - NagerDateHolidayProvider: Uses the Nager.Date public API
      (https://date.nager.at/) — free, no key required, covers 100+ countries.
    - StaticHolidayProvider: Returns holidays from a fixed list — useful for
      testing or environments without internet access.

To add a new provider (e.g., a commercial holiday API, a government data
source, or a customer-specific feed), implement the HolidayProvider Protocol
with a fetch_holidays() method returning a list of Holiday objects.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx


@dataclass(frozen=True)
class Holiday:
    """A single holiday entry."""

    date: datetime.date
    name: str
    country_code: str


@runtime_checkable
class HolidayProvider(Protocol):
    """Abstract interface for fetching public holidays.

    Any implementation must provide fetch_holidays() returning holidays
    for a given country and year. The provider is swappable: configure
    via dependency injection or environment variable, never hardcoded
    in detection or calendar-import logic.
    """

    def fetch_holidays(self, country_code: str, year: int) -> list[Holiday]: ...


class NagerDateHolidayProvider:
    """Fetches public holidays from the Nager.Date API.

    API docs: https://date.nager.at/swagger/index.html
    No API key required. Rate-limited to reasonable usage.
    Covers 100+ countries.

    This is the default provider. To swap it, implement the
    HolidayProvider Protocol and inject the replacement.
    """

    BASE_URL = "https://date.nager.at/api/v3"

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def fetch_holidays(self, country_code: str, year: int) -> list[Holiday]:
        url = f"{self.BASE_URL}/PublicHolidays/{year}/{country_code}"
        response = httpx.get(url, timeout=self._timeout)
        response.raise_for_status()

        holidays: list[Holiday] = []
        for entry in response.json():
            holidays.append(
                Holiday(
                    date=datetime.date.fromisoformat(entry["date"]),
                    name=entry["localName"],
                    country_code=country_code,
                )
            )
        return holidays


class StaticHolidayProvider:
    """Returns holidays from a pre-configured list.

    Useful for testing, offline environments, or customer-specific
    holiday schedules not covered by a public API.
    """

    def __init__(self, holidays: list[Holiday]) -> None:
        self._holidays = holidays

    def fetch_holidays(self, country_code: str, year: int) -> list[Holiday]:
        return [h for h in self._holidays if h.country_code == country_code and h.date.year == year]
