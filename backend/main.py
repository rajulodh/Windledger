from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

API_ROOT = "https://data.elexon.co.uk/bmrs/api/v1/datasets"
MONTH_START = date(2026, 1, 1)
MONTH_END = date(2026, 2, 1)
CALIBRATION_WINDOW_DAYS = 30
HISTORY_START = MONTH_START - timedelta(days=CALIBRATION_WINDOW_DAYS)
FORECAST_LOOKBACK = HISTORY_START - timedelta(days=2)
UTC = timezone.utc
FRONTEND_DIST = Path(
    os.environ.get(
        "FRONTEND_DIST",
        str(Path(__file__).resolve().parent.parent / "frontend" / "dist"),
    )
)


class ElexonDataError(RuntimeError):
    """Raised when an Elexon stream cannot provide a valid response."""


def _request_records(dataset: str, params: dict[str, str]) -> list[dict[str, Any]]:
    url = f"{API_ROOT}/{dataset}/stream?{urlencode(params)}"
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "WindLedger/1.0"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            payload = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ElexonDataError(f"Elexon {dataset} request failed: {error}") from error
    if not isinstance(payload, list):
        raise ElexonDataError(f"Elexon {dataset} returned an unexpected response shape.")
    if any(not isinstance(record, dict) for record in payload):
        raise ElexonDataError(f"Elexon {dataset} returned a non-object record.")
    return payload


def _iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Expected timezone-aware timestamp, received {value!r}.")
    return parsed.astimezone(UTC)


def _generation(record: dict[str, Any], dataset: str) -> float:
    value = record.get("generation")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ElexonDataError(f"Elexon {dataset} record has invalid generation: {value!r}.")
    number = float(value)
    if not math.isfinite(number):
        raise ElexonDataError(f"Elexon {dataset} record has non-finite generation.")
    return number


def _fetch_month_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    actual_params = {
        "settlementDateFrom": HISTORY_START.isoformat(),
        "settlementDateTo": MONTH_END.isoformat(),
        "fuelType": "WIND",
    }
    forecast_from = datetime.combine(FORECAST_LOOKBACK, time.min, tzinfo=UTC)
    forecast_to = datetime.combine(MONTH_END, time.min, tzinfo=UTC)
    forecast_params = {
        "publishDateTimeFrom": forecast_from.isoformat().replace("+00:00", "Z"),
        "publishDateTimeTo": forecast_to.isoformat().replace("+00:00", "Z"),
    }
    with ThreadPoolExecutor(max_workers=2) as executor:
        actuals_task = executor.submit(_request_records, "FUELHH", actual_params)
        forecasts_task = executor.submit(_request_records, "WINDFOR", forecast_params)
        return actuals_task.result(), forecasts_task.result()


def _hour_start(timestamp: datetime) -> datetime:
    return timestamp.replace(minute=0, second=0, microsecond=0)


def _lead_bin(lead_hours: float) -> str | None:
    if lead_hours < 0:
        return None
    if lead_hours < 12:
        return "0-12h"
    if lead_hours < 24:
        return "12-24h"
    if lead_hours < 36:
        return "24-36h"
    if lead_hours < 48:
        return "36-48h"
    return "48h+"


def _day_ahead_cutoff(delivery_date: date) -> datetime:
    """N2EX GB day-ahead gate closure: 09:50 UK time on D-1.

    The January 2026 replay and its December training window are both in GMT,
    so UK local time is UTC for every date used by this pilot.
    """
    cutoff_day = delivery_date - timedelta(days=1)
    return datetime.combine(cutoff_day, time(hour=9, minute=50), tzinfo=UTC)


def _calculate_metrics(
    points: list[dict[str, Any]], forecast_key: str = "forecast_mw"
) -> dict[str, float | int | None]:
    matched = [
        point
        for point in points
        if point[forecast_key] is not None and point["actual_mw"] is not None
    ]
    errors = [point[forecast_key] - point["actual_mw"] for point in matched]
    absolute_errors = [abs(error) for error in errors]
    actual_total = sum(point["actual_mw"] for point in matched)
    return {
        "matched_hours": len(matched),
        "mae_mw": round(sum(absolute_errors) / len(matched), 1) if matched else None,
        "rmse_mw": round(math.sqrt(sum(error**2 for error in errors) / len(matched)), 1)
        if matched
        else None,
        "bias_mw": round(sum(errors) / len(matched), 1) if matched else None,
        "wape_pct": round(sum(absolute_errors) / actual_total * 100, 2)
        if matched and actual_total
        else None,
    }


def build_month_payload(
    actual_records: list[dict[str, Any]],
    forecast_records: list[dict[str, Any]],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    actual_by_period: dict[datetime, list[tuple[datetime, float]]] = defaultdict(list)
    for record in actual_records:
        if record.get("fuelType") != "WIND":
            continue
        start_time = _iso_datetime(record["startTime"])
        if HISTORY_START <= start_time.date() < MONTH_END:
            actual_by_period[start_time].append(
                (_iso_datetime(record["publishTime"]), _generation(record, "FUELHH"))
            )

    forecasts_by_hour: dict[datetime, list[tuple[datetime, float]]] = defaultdict(list)
    for record in forecast_records:
        start_time = _iso_datetime(record["startTime"])
        if HISTORY_START <= start_time.date() < MONTH_END:
            publish_time = _iso_datetime(record["publishTime"])
            forecasts_by_hour[_hour_start(start_time)].append(
                (publish_time, _generation(record, "WINDFOR"))
            )

    daily_forecasts: dict[
        date, tuple[datetime | None, dict[datetime, float]]
    ] = {}
    for day_offset in range((MONTH_END - HISTORY_START).days):
        delivery_date = HISTORY_START + timedelta(days=day_offset)
        day_boundary = datetime.combine(delivery_date, time.min, tzinfo=UTC)
        decision_cutoff = _day_ahead_cutoff(delivery_date)
        day_end = day_boundary + timedelta(days=1)
        issue_times = [
            publish_time
            for start_time, records in forecasts_by_hour.items()
            if day_boundary <= start_time < day_end
            for publish_time, _ in records
            if publish_time < decision_cutoff
        ]
        latest_issue = max(issue_times) if issue_times else None
        issue_values: dict[datetime, float] = {}
        if latest_issue is not None:
            for hour in range(24):
                start_time = day_boundary + timedelta(hours=hour)
                value = next(
                    (
                        generation
                        for published, generation in forecasts_by_hour.get(start_time, [])
                        if published == latest_issue
                    ),
                    None,
                )
                if value is not None:
                    issue_values[start_time] = value
        daily_forecasts[delivery_date] = (latest_issue, issue_values)

    def actual_hourly_for_day(
        delivery_date: date, available_before: datetime | None = None
    ) -> dict[datetime, float]:
        day_start = datetime.combine(delivery_date, time.min, tzinfo=UTC)
        result: dict[datetime, list[float]] = defaultdict(list)
        for period_start in (day_start + timedelta(minutes=minute) for minute in range(0, 1440, 30)):
            candidates = actual_by_period.get(period_start, [])
            available = [
                (published, generation)
                for published, generation in candidates
                if available_before is None or published < available_before
            ]
            if available:
                latest_actual = max(available, key=lambda record: record[0])[1]
                result[_hour_start(period_start)].append(latest_actual)
        return {
            hour_start: sum(values) / len(values)
            for hour_start, values in result.items()
        }

    historical_actuals_as_of: dict[tuple[date, datetime], dict[datetime, float]] = {}
    days: list[dict[str, Any]] = []
    for day_offset in range((MONTH_END - MONTH_START).days):
        delivery_date = MONTH_START + timedelta(days=day_offset)
        day_boundary = datetime.combine(delivery_date, time.min, tzinfo=UTC)
        decision_cutoff = _day_ahead_cutoff(delivery_date)
        latest_issue, issue_values = daily_forecasts.get(delivery_date, (None, {}))
        actual_hourly = actual_hourly_for_day(delivery_date)

        history_errors: dict[tuple[int, str], list[float]] = defaultdict(list)
        history_days: set[date] = set()
        for history_offset in range(CALIBRATION_WINDOW_DAYS, 0, -1):
            history_date = delivery_date - timedelta(days=history_offset)
            history_issue, history_values = daily_forecasts.get(history_date, (None, {}))
            if history_issue is None:
                continue
            actual_cache_key = (history_date, decision_cutoff)
            if actual_cache_key not in historical_actuals_as_of:
                historical_actuals_as_of[actual_cache_key] = actual_hourly_for_day(
                    history_date, available_before=decision_cutoff
                )
            historic_actuals = historical_actuals_as_of[actual_cache_key]
            matched_history = False
            for start_time, forecast_mw in history_values.items():
                actual_mw = historic_actuals.get(start_time)
                if actual_mw is None:
                    continue
                lead_hours = (start_time - history_issue).total_seconds() / 3600
                lead_group = _lead_bin(lead_hours)
                if lead_group is None:
                    continue
                history_errors[(start_time.hour, lead_group)].append(forecast_mw - actual_mw)
                matched_history = True
            if matched_history:
                history_days.add(history_date)

        points: list[dict[str, Any]] = []
        for hour in range(24):
            start_time = day_boundary + timedelta(hours=hour)
            forecast_mw = issue_values.get(start_time)
            actual_mw = actual_hourly.get(start_time)
            lead_hours = (
                (start_time - latest_issue).total_seconds() / 3600
                if latest_issue is not None and forecast_mw is not None
                else None
            )
            lead_group = _lead_bin(lead_hours) if lead_hours is not None else None
            estimated_bias = None
            calibrated_mw = None
            if forecast_mw is not None and len(history_days) >= CALIBRATION_WINDOW_DAYS:
                estimated_bias = sum(history_errors.get((hour, lead_group), [])) / len(
                    history_errors.get((hour, lead_group), [])
                ) if history_errors.get((hour, lead_group)) else 0.0
                calibrated_mw = max(0.0, forecast_mw - estimated_bias)
            points.append(
                {
                    "start_time": start_time.isoformat().replace("+00:00", "Z"),
                    "forecast_mw": round(forecast_mw, 1) if forecast_mw is not None else None,
                    "estimated_bias_mw": round(estimated_bias, 1)
                    if estimated_bias is not None
                    else None,
                    "calibrated_forecast_mw": round(calibrated_mw, 1)
                    if calibrated_mw is not None
                    else None,
                    "actual_mw": round(actual_mw, 1) if actual_mw is not None else None,
                    "lead_hours": round(lead_hours, 1) if lead_hours is not None else None,
                    "lead_bin": lead_group,
                    "forecast_publish_time": latest_issue.isoformat().replace("+00:00", "Z")
                    if latest_issue is not None and forecast_mw is not None
                    else None,
                }
            )
        days.append(
            {
                "delivery_date": delivery_date.isoformat(),
                "forecast_publish_time": latest_issue.isoformat().replace("+00:00", "Z")
                if latest_issue is not None
                else None,
                "calibration_training_days": len(history_days),
                "metrics": _calculate_metrics(points),
                "calibrated_metrics": _calculate_metrics(
                    points, forecast_key="calibrated_forecast_mw"
                ),
                "points": points,
            }
        )

    all_points = [point for day in days for point in day["points"]]
    calibrated_points = [
        point
        for point in all_points
        if point["calibrated_forecast_mw"] is not None and point["actual_mw"] is not None
    ]
    matched_hours = sum(day["metrics"]["matched_hours"] for day in days)
    actual_hours = sum(point["actual_mw"] is not None for point in all_points)
    forecast_hours = sum(point["forecast_mw"] is not None for point in all_points)
    lead_time_metrics = []
    for lead_group in ("0-12h", "12-24h", "24-36h", "36-48h", "48h+"):
        group_points = [
            point
            for point in calibrated_points
            if point["lead_bin"] == lead_group
        ]
        if group_points:
            lead_time_metrics.append(
                {
                    "lead_bin": lead_group,
                    "raw_metrics": _calculate_metrics(group_points),
                    "calibrated_metrics": _calculate_metrics(
                        group_points, forecast_key="calibrated_forecast_mw"
                    ),
                }
            )
    return {
        "month": "2026-01",
        "timezone": "Europe/London",
        "generated_at": (generated_at or datetime.now(UTC))
        .astimezone(UTC)
        .isoformat()
        .replace("+00:00", "Z"),
        "source": {
            "actuals": f"{API_ROOT}/FUELHH/stream",
            "forecasts": f"{API_ROOT}/WINDFOR/stream",
        },
        "method": {
            "forecast_cutoff": (
                "Latest WINDFOR publishTime strictly before 09:50 UK time on the "
                "previous calendar day (N2EX GB day-ahead gate closure; 09:50 UTC "
                "for this January 2026 replay)."
            ),
            "actuals_alignment": "Hourly mean of FUELHH half-hourly WIND generation.",
            "calibration": (
                f"Rolling {CALIBRATION_WINDOW_DAYS}-day mean forecast error by UTC delivery "
                "hour and forecast lead-time bin. Historical FUELHH values are limited "
                "to records published before the test day's 09:50 UK decision cutoff."
            ),
        },
        "coverage": {
            "delivery_days": len(days),
            "forecast_hours": forecast_hours,
            "actual_hours": actual_hours,
            "matched_hours": matched_hours,
            "calibrated_hours": len(calibrated_points),
        },
        "monthly_metrics": _calculate_metrics(all_points),
        "comparison_raw_metrics": _calculate_metrics(
            calibrated_points, forecast_key="forecast_mw"
        ),
        "calibrated_metrics": _calculate_metrics(
            calibrated_points, forecast_key="calibrated_forecast_mw"
        ),
        "calibration": {
            "window_days": CALIBRATION_WINDOW_DAYS,
            "lead_time_metrics": lead_time_metrics,
            "method": (
                "Walk-forward evaluation; correction is mean historical forecast-minus-actual "
                "error for the same delivery hour and lead-time bin. Corrected MW is clipped "
                "at zero. No correction is applied until a full 30 prior delivery days are usable."
            ),
        },
        "days": days,
    }


@lru_cache(maxsize=1)
def _cached_month_payload() -> dict[str, Any]:
    try:
        actual_records, forecast_records = _fetch_month_records()
        return build_month_payload(actual_records, forecast_records)
    except ElexonDataError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(
            status_code=502,
            detail=f"Elexon data could not be interpreted: {error}",
        ) from error


app = FastAPI(title="Wind Ledger API", version="1.0.0")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/month")
def get_month() -> dict[str, Any]:
    return _cached_month_payload()


@app.get("/api/day")
def get_day(delivery_date: date = Query(...)) -> dict[str, Any]:
    if not MONTH_START <= delivery_date < MONTH_END:
        raise HTTPException(status_code=422, detail="delivery_date must be in January 2026.")
    payload = _cached_month_payload()
    return next(
        day for day in payload["days"] if day["delivery_date"] == delivery_date.isoformat()
    )


if FRONTEND_DIST.is_dir():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def serve_frontend(path: str) -> FileResponse:
        index_file = FRONTEND_DIST / "index.html"
        if not index_file.is_file():
            raise HTTPException(status_code=404, detail="Frontend build is not available.")
        return FileResponse(index_file)
