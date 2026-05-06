from __future__ import annotations

from src.alerts import build_digest, evaluate_threshold_alerts
from src.data_quality import run_data_quality_checks
from src.db import default_db_path, get_connection
from src.kpi_contract import DEFAULT_THRESHOLDS
from src.reporting_queries import owner_metrics, parts_metrics, service_metrics
from src.semantic_model import initialize_curated_views


def test_curated_layer_and_quality_checks_run():
    conn = get_connection(default_db_path())
    initialize_curated_views(conn)
    checks = run_data_quality_checks(conn)
    assert len(checks) > 0
    assert "check_name" in checks.columns


def test_core_metrics_and_alerts_run():
    conn = get_connection(default_db_path())
    owner = owner_metrics(conn, "2024-01-01", "2025-12-31", 350000.0)
    service = service_metrics(conn, "2024-01-01", "2025-12-31")
    parts = parts_metrics(conn, "2024-01-01", "2025-12-31")

    metric_values = {
        "service_absorption_proxy_pct": owner["service_absorption_proxy_pct"],
        "technician_efficiency_pct": service["technician_efficiency_pct"],
        "open_work_orders_14_plus": float(service["open_work_orders_14_plus"]),
        "parts_turn_r12": parts["parts_turn_r12"],
        "dead_stock_ratio_pct": parts["dead_stock_ratio_pct"],
    }
    alerts = evaluate_threshold_alerts(metric_values, DEFAULT_THRESHOLDS)
    digest = build_digest("weekly", metric_values, alerts)

    assert len(alerts) >= 5
    assert "Digest" in digest
