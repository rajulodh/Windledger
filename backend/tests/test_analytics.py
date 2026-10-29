import unittest
from datetime import date, datetime, timedelta, timezone

from backend.main import build_month_payload


class MonthAnalyticsTests(unittest.TestCase):
    def test_selects_latest_complete_issue_before_n2ex_gate_closure(self) -> None:
        actuals = [
            {
                "fuelType": "WIND",
                "startTime": "2026-01-05T00:00:00Z",
                "publishTime": "2026-01-05T00:30:00Z",
                "generation": 100,
            },
            {
                "fuelType": "WIND",
                "startTime": "2026-01-05T00:30:00Z",
                "publishTime": "2026-01-05T01:00:00Z",
                "generation": 120,
            },
        ]
        forecasts = [
            {"startTime": "2026-01-05T00:00:00Z", "publishTime": "2026-01-04T08:00:00Z", "generation": 90},
            {"startTime": "2026-01-05T00:00:00Z", "publishTime": "2026-01-04T09:00:00Z", "generation": 110},
            {"startTime": "2026-01-05T00:00:00Z", "publishTime": "2026-01-04T10:00:00Z", "generation": 999},
        ]

        payload = build_month_payload(actuals, forecasts)

        day = payload["days"][4]
        self.assertEqual(day["points"][0]["forecast_mw"], 110)
        self.assertEqual(day["points"][0]["actual_mw"], 110)
        self.assertEqual(day["points"][0]["forecast_publish_time"], "2026-01-04T09:00:00Z")
        self.assertEqual(day["metrics"]["matched_hours"], 1)
        self.assertEqual(day["metrics"]["mae_mw"], 0)
        self.assertEqual(day["metrics"]["wape_pct"], 0)

    def test_does_not_mix_issue_times_when_latest_issue_has_missing_hour(self) -> None:
        forecasts = [
            {"startTime": "2026-01-05T00:00:00Z", "publishTime": "2026-01-04T08:00:00Z", "generation": 90},
            {"startTime": "2026-01-05T01:00:00Z", "publishTime": "2026-01-04T08:00:00Z", "generation": 95},
            {"startTime": "2026-01-05T00:00:00Z", "publishTime": "2026-01-04T09:00:00Z", "generation": 110},
        ]

        day = build_month_payload([], forecasts)["days"][4]

        self.assertEqual(day["points"][0]["forecast_mw"], 110)
        self.assertIsNone(day["points"][1]["forecast_mw"])
        self.assertEqual(day["forecast_publish_time"], "2026-01-04T09:00:00Z")

    def test_filters_non_wind_actuals_and_month_boundary(self) -> None:
        actuals = [
            {
                "fuelType": "WIND",
                "startTime": "2025-12-31T23:30:00Z",
                "publishTime": "2026-01-01T00:00:00Z",
                "generation": 10,
            },
            {"fuelType": "GAS", "startTime": "2026-01-01T00:00:00Z", "generation": 500},
            {
                "fuelType": "WIND",
                "startTime": "2026-02-01T00:00:00Z",
                "publishTime": "2026-02-01T00:30:00Z",
                "generation": 20,
            },
        ]

        payload = build_month_payload(actuals, [])

        self.assertEqual(payload["coverage"]["actual_hours"], 0)
        self.assertIsNone(payload["days"][0]["points"][0]["actual_mw"])

    def test_metrics_use_forecast_minus_actual_for_bias(self) -> None:
        actuals = [
            {
                "fuelType": "WIND",
                "startTime": "2026-01-01T00:00:00Z",
                "publishTime": "2026-01-01T00:30:00Z",
                "generation": 80,
            },
            {
                "fuelType": "WIND",
                "startTime": "2026-01-01T00:30:00Z",
                "publishTime": "2026-01-01T01:00:00Z",
                "generation": 100,
            },
        ]
        forecasts = [
            {"startTime": "2026-01-01T00:00:00Z", "publishTime": "2025-12-31T09:00:00Z", "generation": 120}
        ]

        metrics = build_month_payload(actuals, forecasts)["days"][0]["metrics"]

        self.assertEqual(metrics["bias_mw"], 30)
        self.assertEqual(metrics["mae_mw"], 30)
        self.assertEqual(metrics["rmse_mw"], 30)
        self.assertAlmostEqual(metrics["wape_pct"], 33.33, places=2)

    def test_walk_forward_calibration_uses_only_prior_published_actuals(self) -> None:
        actuals = []
        forecasts = []
        first_history_day = date(2025, 12, 2)
        for offset in range(31):
            delivery_day = first_history_day + timedelta(days=offset)
            day_start = datetime.combine(delivery_day, datetime.min.time(), tzinfo=timezone.utc)
            day_text = delivery_day.isoformat()
            issue_text = (day_start - timedelta(days=1) + timedelta(hours=9)).isoformat().replace("+00:00", "Z")
            forecasts.append(
                {
                    "startTime": f"{day_text}T00:00:00Z",
                    "publishTime": issue_text,
                    "generation": 120,
                }
            )
            actuals.append(
                {
                    "fuelType": "WIND",
                    "startTime": f"{day_text}T00:00:00Z",
                    "publishTime": f"{day_text}T00:30:00Z",
                    "generation": 100,
                }
            )

        payload = build_month_payload(actuals, forecasts)
        first_january_day = payload["days"][0]

        self.assertEqual(first_january_day["calibration_training_days"], 30)
        self.assertEqual(first_january_day["points"][0]["estimated_bias_mw"], 20)
        self.assertEqual(first_january_day["points"][0]["calibrated_forecast_mw"], 100)
        self.assertEqual(first_january_day["metrics"]["mae_mw"], 20)
        self.assertEqual(first_january_day["calibrated_metrics"]["mae_mw"], 0)

    def test_calibration_is_not_applied_without_thirty_prior_days(self) -> None:
        actuals = [
            {
                "fuelType": "WIND",
                "startTime": "2026-01-01T00:00:00Z",
                "publishTime": "2026-01-01T00:30:00Z",
                "generation": 100,
            }
        ]
        forecasts = [
            {
                "startTime": "2026-01-01T00:00:00Z",
                "publishTime": "2025-12-31T09:00:00Z",
                "generation": 120,
            }
        ]

        point = build_month_payload(actuals, forecasts)["days"][0]["points"][0]

        self.assertIsNone(point["estimated_bias_mw"])
        self.assertIsNone(point["calibrated_forecast_mw"])

    def test_walk_forward_excludes_actuals_published_at_or_after_test_cutoff(self) -> None:
        actuals = []
        forecasts = []
        first_history_day = date(2025, 12, 2)
        for offset in range(30):
            delivery_day = first_history_day + timedelta(days=offset)
            day_text = delivery_day.isoformat()
            issue_time = datetime.combine(
                delivery_day, datetime.min.time(), tzinfo=timezone.utc
            ) - timedelta(days=1) + timedelta(hours=9)
            forecasts.append(
                {
                    "startTime": f"{day_text}T00:00:00Z",
                    "publishTime": issue_time.isoformat().replace("+00:00", "Z"),
                    "generation": 120,
                }
            )
            actual_publish_time = (
                "2026-01-01T10:00:00Z"
                if offset == 0
                else f"{day_text}T00:30:00Z"
            )
            actuals.append(
                {
                    "fuelType": "WIND",
                    "startTime": f"{day_text}T00:00:00Z",
                    "publishTime": actual_publish_time,
                    "generation": 100,
                }
            )
        forecasts.append(
            {
                "startTime": "2026-01-01T00:00:00Z",
                "publishTime": "2025-12-31T09:00:00Z",
                "generation": 120,
            }
        )
        actuals.append(
            {
                "fuelType": "WIND",
                "startTime": "2026-01-01T00:00:00Z",
                "publishTime": "2026-01-01T00:30:00Z",
                "generation": 100,
            }
        )

        payload = build_month_payload(actuals, forecasts)

        self.assertEqual(payload["days"][0]["calibration_training_days"], 29)
        self.assertIsNone(payload["days"][0]["points"][0]["calibrated_forecast_mw"])


if __name__ == "__main__":
    unittest.main()
