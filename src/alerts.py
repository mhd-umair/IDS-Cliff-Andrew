from __future__ import annotations

from datetime import datetime

import pandas as pd


def evaluate_threshold_alerts(metric_values: dict[str, float], thresholds: dict[str, dict]) -> pd.DataFrame:
    rows: list[dict] = []
    for metric_id, cfg in thresholds.items():
        value = float(metric_values.get(metric_id, 0))
        severity = "ok"
        message = "On target"
        if "critical_below" in cfg and value < cfg["critical_below"]:
            severity, message = "critical", f"{metric_id} is critically low ({value:.1f})"
        elif "warn_below" in cfg and value < cfg["warn_below"]:
            severity, message = "warning", f"{metric_id} is below target ({value:.1f})"
        elif "critical_above" in cfg and value > cfg["critical_above"]:
            severity, message = "critical", f"{metric_id} is critically high ({value:.1f})"
        elif "warn_above" in cfg and value > cfg["warn_above"]:
            severity, message = "warning", f"{metric_id} is above target ({value:.1f})"

        rows.append(
            {
                "metric_id": metric_id,
                "value": round(value, 2),
                "severity": severity,
                "message": message,
            }
        )
    return pd.DataFrame(rows).sort_values(["severity", "metric_id"], ascending=[True, True])


def build_digest(cadence: str, metric_values: dict[str, float], alerts: pd.DataFrame) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    warning_count = int((alerts["severity"] == "warning").sum()) if not alerts.empty else 0
    critical_count = int((alerts["severity"] == "critical").sum()) if not alerts.empty else 0

    lines = [
        f"{cadence.title()} Dealership KPI Digest",
        f"Generated: {now}",
        "",
        "Top metrics:",
        f"- Service absorption (proxy): {metric_values.get('service_absorption_proxy_pct', 0):.1f}%",
        f"- Tech efficiency: {metric_values.get('technician_efficiency_pct', 0):.1f}%",
        f"- Open WO 14+ days: {metric_values.get('open_work_orders_14_plus', 0):.0f}",
        f"- Parts turns (proxy): {metric_values.get('parts_turn_r12', 0):.2f}",
        f"- Dead stock ratio: {metric_values.get('dead_stock_ratio_pct', 0):.1f}%",
        "",
        f"Alerts: {critical_count} critical, {warning_count} warning",
    ]
    return "\n".join(lines)
