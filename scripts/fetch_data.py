"""Fetch and merge Nigeria macroeconomic dashboard data."""

from __future__ import annotations

import copy
import json
import logging
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT_DIR / "data" / "data.json"
TEMP_DATA_PATH = DATA_PATH.with_suffix(".json.tmp")

WORLD_BANK_BASE_URL = (
    "https://api.worldbank.org/v2/country/NG/indicator/{indicator}"
)
EIA_BRENT_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
EIA_INTERNATIONAL_URL = "https://api.eia.gov/v2/international/data/"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"

HISTORY_LIMIT = 24
TIMEOUT_SECONDS = 30

logger = logging.getLogger("nigeria_macro_pipeline")


class SourceFailure(Exception):
    """Raised when an API source cannot produce a usable result."""


def configure_logging() -> None:
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


def load_data() -> dict[str, Any]:
    with DATA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(data: dict[str, Any]) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TEMP_DATA_PATH.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    TEMP_DATA_PATH.replace(DATA_PATH)


def compute_next_update(today: datetime) -> str:
    if today.day < 15:
        return today.replace(day=15).strftime("%Y-%m-%d")

    year = today.year + 1 if today.month == 12 else today.year
    month = 1 if today.month == 12 else today.month + 1
    return today.replace(year=year, month=month, day=1).strftime("%Y-%m-%d")


def update_meta(data: dict[str, Any]) -> None:
    today = datetime.utcnow()
    data.setdefault("meta", {})
    data["meta"]["lastUpdated"] = today.strftime("%Y-%m-%d")
    data["meta"]["nextUpdate"] = compute_next_update(today)
    data["meta"]["updateFrequency"] = "bi-weekly"
    data["meta"]["timezone"] = "UTC"


def get_indicator(data: dict[str, Any], name: str) -> dict[str, Any]:
    return data["indicators"][name]


def mark_stale(data: dict[str, Any], name: str) -> None:
    indicator = get_indicator(data, name)
    if indicator.get("note") == "manual_update":
        return
    indicator["stale"] = True


def compute_trend(current: Any, previous: Any) -> str:
    if current is None or previous is None:
        return "neutral"
    if current > previous:
        return "up"
    if current < previous:
        return "down"
    return "neutral"


def capped_history(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return entries[-HISTORY_LIMIT:]


def update_indicator(
    data: dict[str, Any],
    name: str,
    *,
    current: float | None,
    previous: float | None,
    period: str | None,
    history: list[dict[str, Any]],
) -> None:
    indicator = get_indicator(data, name)
    if indicator.get("note") == "manual_update":
        logger.info("%s skipped manual_update indicator", name)
        return

    indicator["current"] = current
    indicator["previous"] = previous
    indicator["period"] = period
    indicator["trend"] = compute_trend(current, previous)
    indicator["stale"] = False
    indicator["history"] = capped_history(history)


def response_json(response: requests.Response, indicator: str) -> Any:
    if response.status_code >= 400:
        raise SourceFailure(f"{indicator} HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise SourceFailure(f"{indicator} invalid JSON: {exc}") from exc


def fetch_world_bank_indicator(indicator_name: str, code: str) -> list[dict[str, Any]]:
    try:
        response = requests.get(
            WORLD_BANK_BASE_URL.format(indicator=code),
            params={"format": "json", "per_page": 10, "mrv": 10},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise SourceFailure(f"{indicator_name} request failed: {exc}") from exc
    payload = response_json(response, indicator_name)
    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        raise SourceFailure(f"{indicator_name} unexpected World Bank response")

    rows = [
        {"period": str(row["date"]), "value": row["value"]}
        for row in payload[1]
        if row.get("value") is not None and row.get("date") is not None
    ]
    if not rows:
        raise SourceFailure(f"{indicator_name} no non-null World Bank values")
    return rows


def fetch_world_bank(data: dict[str, Any]) -> None:
    external = fetch_world_bank_indicator("externalReserves", "FI.RES.TOTL.CD")
    external_history = [
        {"period": row["period"], "value": round(float(row["value"]) / 1_000_000_000, 2)}
        for row in reversed(external)
    ]
    external_latest = external_history[-1]
    external_previous = external_history[-2] if len(external_history) > 1 else None
    update_indicator(
        data,
        "externalReserves",
        current=external_latest["value"],
        previous=external_previous["value"] if external_previous else None,
        period=external_latest["period"],
        history=external_history,
    )
    logger.info("externalReserves fetched successfully from World Bank HTTP 200")

    debt = fetch_world_bank_indicator("publicDebt", "GC.DOD.TOTL.GD.ZS")
    debt_history = [
        {"period": row["period"], "value": round(float(row["value"]), 1)}
        for row in reversed(debt)
    ]
    debt_latest = debt_history[-1]
    debt_previous = debt_history[-2] if len(debt_history) > 1 else None
    update_indicator(
        data,
        "publicDebt",
        current=debt_latest["value"],
        previous=debt_previous["value"] if debt_previous else None,
        period=debt_latest["period"],
        history=debt_history,
    )
    logger.info("publicDebt fetched successfully from World Bank HTTP 200")

    inflation = fetch_world_bank_indicator("inflationTrend", "FP.CPI.TOTL.ZG")
    inflation_history = [
        {"period": row["period"], "value": round(float(row["value"]), 1)}
        for row in reversed(inflation)
    ]
    inflation_latest = inflation_history[-1]
    inflation_previous = inflation_history[-2] if len(inflation_history) > 1 else None
    update_indicator(
        data,
        "inflationTrend",
        current=inflation_latest["value"],
        previous=inflation_previous["value"] if inflation_previous else None,
        period=inflation_latest["period"],
        history=inflation_history,
    )
    logger.info("inflationTrend fetched successfully from World Bank HTTP 200")


def parse_eia_rows(payload: dict[str, Any], indicator_name: str) -> list[dict[str, Any]]:
    rows = payload.get("response", {}).get("data")
    if not isinstance(rows, list):
        raise SourceFailure(f"{indicator_name} unexpected EIA response")

    parsed = []
    for row in rows:
        period = row.get("period")
        value = row.get("value")
        if period is None or value in (None, ""):
            continue
        parsed.append({"period": str(period)[:7], "value": float(value)})

    if not parsed:
        raise SourceFailure(f"{indicator_name} no non-null EIA values")
    return parsed


def fetch_eia_endpoint(
    url: str, params: list[tuple[str, str]], indicator_name: str
) -> list[dict[str, Any]]:
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise SourceFailure(f"{indicator_name} request failed: {exc}") from exc
    payload = response_json(response, indicator_name)
    return parse_eia_rows(payload, indicator_name)


def fetch_eia(data: dict[str, Any]) -> None:
    api_key = os.environ.get("EIA_API_KEY")
    if not api_key:
        raise SourceFailure("oilPrice/oilProduction EIA_API_KEY missing")

    brent_rows = fetch_eia_endpoint(
        EIA_BRENT_URL,
        [
            ("api_key", api_key),
            ("frequency", "monthly"),
            ("data[0]", "value"),
            ("facets[series][]", "RBRTE"),
            ("sort[0][column]", "period"),
            ("sort[0][direction]", "desc"),
            ("length", "6"),
        ],
        "oilPrice",
    )
    brent_history = [
        {"period": row["period"], "value": round(row["value"], 2)}
        for row in reversed(brent_rows)
    ]
    brent_current = brent_rows[0]
    brent_previous = brent_rows[1] if len(brent_rows) > 1 else None
    update_indicator(
        data,
        "oilPrice",
        current=round(brent_current["value"], 2),
        previous=round(brent_previous["value"], 2) if brent_previous else None,
        period=brent_current["period"],
        history=brent_history,
    )
    logger.info("oilPrice fetched successfully from EIA HTTP 200")

    production_rows = fetch_eia_endpoint(
        EIA_INTERNATIONAL_URL,
        [
            ("api_key", api_key),
            ("frequency", "monthly"),
            ("data[0]", "value"),
            ("facets[activityId][]", "1"),
            ("facets[productId][]", "53"),
            ("facets[countryRegionId][]", "NGA"),
            ("sort[0][column]", "period"),
            ("sort[0][direction]", "desc"),
            ("length", "6"),
        ],
        "oilProduction",
    )
    production_history = [
        {"period": row["period"], "value": round(row["value"] / 1000, 3)}
        for row in reversed(production_rows)
    ]
    production_current = production_rows[0]
    production_previous = production_rows[1] if len(production_rows) > 1 else None
    update_indicator(
        data,
        "oilProduction",
        current=round(production_current["value"] / 1000, 3),
        previous=round(production_previous["value"] / 1000, 3)
        if production_previous
        else None,
        period=production_current["period"],
        history=production_history,
    )
    logger.info("oilProduction fetched successfully from EIA HTTP 200")


def fetch_alpha_vantage(data: dict[str, Any]) -> None:
    api_key = os.environ.get("ALPHA_VANTAGE_KEY")
    if not api_key:
        raise SourceFailure("exchangeRate ALPHA_VANTAGE_KEY missing")

    try:
        response = requests.get(
            ALPHA_VANTAGE_URL,
            params={
                "function": "FX_MONTHLY",
                "from_symbol": "USD",
                "to_symbol": "NGN",
                "apikey": api_key,
            },
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise SourceFailure(f"exchangeRate request failed: {exc}") from exc
    payload = response_json(response, "exchangeRate")
    if "Note" in payload or "Information" in payload:
        raise SourceFailure("exchangeRate Alpha Vantage rate limit or information response")

    series = payload.get("Time Series FX (Monthly)")
    if not isinstance(series, dict):
        raise SourceFailure("exchangeRate unexpected Alpha Vantage response")

    dates = sorted(series.keys(), reverse=True)
    values = []
    for date in dates:
        close = series.get(date, {}).get("4. close")
        if close in (None, ""):
            continue
        values.append({"period": date[:7], "value": round(float(close), 2)})

    if not values:
        raise SourceFailure("exchangeRate no non-null Alpha Vantage values")

    current = values[0]
    previous = values[1] if len(values) > 1 else None
    update_indicator(
        data,
        "exchangeRate",
        current=current["value"],
        previous=previous["value"] if previous else None,
        period=current["period"],
        history=list(reversed(values[:12])),
    )
    logger.info("exchangeRate fetched successfully from Alpha Vantage HTTP 200")


def run_source(
    source_name: str,
    data: dict[str, Any],
    source_func: Any,
    stale_indicators: list[str],
) -> bool:
    before = copy.deepcopy(data)
    try:
        source_func(data)
    except Exception as exc:
        data.clear()
        data.update(before)
        for indicator in stale_indicators:
            mark_stale(data, indicator)
        logger.warning("%s failed: %s", source_name, exc)
        return False
    return True


def skip_manual_indicators(data: dict[str, Any]) -> None:
    for name, indicator in data.get("indicators", {}).items():
        if indicator.get("note") == "manual_update":
            logger.info("%s skipped manual_update indicator", name)


def main() -> int:
    configure_logging()
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        message=r"datetime\.datetime\.utcnow\(\) is deprecated.*",
    )
    data = load_data()

    skip_manual_indicators(data)
    source_results = [
        run_source(
            "World Bank",
            data,
            fetch_world_bank,
            ["externalReserves", "publicDebt", "inflationTrend"],
        ),
        run_source("EIA", data, fetch_eia, ["oilPrice", "oilProduction"]),
        run_source("Alpha Vantage", data, fetch_alpha_vantage, ["exchangeRate"]),
    ]

    update_meta(data)
    atomic_write_json(data)

    if not any(source_results):
        logger.warning("all API sources failed; data/data.json preserved with stale flags")
        return 1

    logger.info("data/data.json updated successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
