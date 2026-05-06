from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.alerts import evaluate_threshold_alerts
from src.kpi_contract import DEFAULT_THRESHOLDS, QA_RESPONSE_SCHEMA, SUPPORTED_QUESTION_INTENTS
from src.llm_client import CloudLLMClient
from src.reporting_queries import owner_metrics, parts_metrics, service_metrics


@dataclass
class QAContext:
    start_date: str
    end_date: str
    overhead_target: float


def _parse_metric(question: str) -> str | None:
    q = question.lower()
    if "dead stock" in q:
        return "dead_stock_ratio_pct"
    if "turn" in q and "part" in q:
        return "parts_turn_r12"
    if "efficiency" in q or "tech" in q:
        return "technician_efficiency_pct"
    if "open wo" in q or "work order" in q:
        return "open_work_orders_14_plus"
    if "absorption" in q:
        return "service_absorption_proxy_pct"
    return None


def _parse_intent(question: str) -> str:
    q = question.lower()
    if any(x in q for x in ("compare", "change", "versus", "vs", "improve", "drop")):
        return "period_comparison"
    if any(x in q for x in ("risk", "worry", "alert", "warning", "critical")):
        return "risk_summary"
    return "current_value"


def _metric_snapshot(conn: sqlite3.Connection, ctx: QAContext) -> dict[str, float]:
    owner = owner_metrics(conn, ctx.start_date, ctx.end_date, ctx.overhead_target)
    service = service_metrics(conn, ctx.start_date, ctx.end_date)
    parts = parts_metrics(conn, ctx.start_date, ctx.end_date)
    return {
        "service_absorption_proxy_pct": owner["service_absorption_proxy_pct"],
        "technician_efficiency_pct": service["technician_efficiency_pct"],
        "open_work_orders_14_plus": float(service["open_work_orders_14_plus"]),
        "parts_turn_r12": parts["parts_turn_r12"],
        "dead_stock_ratio_pct": parts["dead_stock_ratio_pct"],
    }


def _previous_context(ctx: QAContext) -> QAContext:
    start = date.fromisoformat(ctx.start_date)
    end = date.fromisoformat(ctx.end_date)
    days = max((end - start).days + 1, 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return QAContext(start_date=prev_start.isoformat(), end_date=prev_end.isoformat(), overhead_target=ctx.overhead_target)


def _fallback_response(question: str, ctx: QAContext) -> dict[str, Any]:
    return {
        "answer": "I can answer KPI-focused questions about service absorption, tech efficiency, work order backlog, parts turns, and dead stock ratio.",
        "evidence": [],
        "period": {"start_date": ctx.start_date, "end_date": ctx.end_date},
        "assumptions": [
            "Question was outside supported intent/metric scope for V1.",
            "No raw SQL generation is enabled in this assistant.",
        ],
        "confidence": "low",
        "suggested_questions": [
            "What is our dead stock ratio in this period?",
            "How did tech efficiency change versus previous period?",
            "Which KPI is currently in critical status?",
        ],
        "meta": {"supported_intents": list(SUPPORTED_QUESTION_INTENTS.keys()), "schema": QA_RESPONSE_SCHEMA, "original_question": question},
    }


def answer_question(
    conn: sqlite3.Connection,
    question: str,
    context: QAContext,
    llm_client: CloudLLMClient | None = None,
    audit_log_path: str | None = None,
) -> dict[str, Any]:
    llm = llm_client or CloudLLMClient()
    intent = _parse_intent(question)
    metric = _parse_metric(question)
    if intent not in SUPPORTED_QUESTION_INTENTS:
        result = _fallback_response(question, context)
        _write_audit(audit_log_path, question, result)
        return result

    current = _metric_snapshot(conn, context)
    alerts = evaluate_threshold_alerts(current, DEFAULT_THRESHOLDS)

    evidence: list[dict[str, Any]] = []
    assumptions: list[str] = [
        "Results are grounded on curated KPI functions only.",
        "Date range comes from dashboard filters unless explicitly changed.",
    ]

    if intent == "risk_summary":
        risky = alerts[alerts["severity"].isin(["warning", "critical"])]
        if risky.empty:
            answer = "All tracked KPIs are currently on target."
            confidence = "high"
        else:
            top = risky.sort_values("severity").head(3).to_dict(orient="records")
            answer = "Top KPI risks are: " + "; ".join(f"{r['metric_id']} ({r['severity']})" for r in top)
            evidence = top
            confidence = "high"
    elif metric is None:
        result = _fallback_response(question, context)
        _write_audit(audit_log_path, question, result)
        return result
    elif intent == "current_value":
        value = current[metric]
        answer = f"Current {metric} is {value:.2f} for the selected period."
        evidence = [{"metric_id": metric, "value": round(value, 4)}]
        confidence = "high"
    else:
        prev_ctx = _previous_context(context)
        prev = _metric_snapshot(conn, prev_ctx)
        cur_value = current[metric]
        prev_value = prev[metric]
        delta = cur_value - prev_value
        answer = (
            f"{metric} changed from {prev_value:.2f} to {cur_value:.2f} "
            f"({delta:+.2f}) versus the previous same-length period."
        )
        evidence = [
            {"metric_id": metric, "current_value": round(cur_value, 4), "previous_value": round(prev_value, 4), "delta": round(delta, 4)},
            {"comparison_period": {"start_date": prev_ctx.start_date, "end_date": prev_ctx.end_date}},
        ]
        confidence = "medium"

    system_prompt = (
        "You are a dealership KPI analyst. Respond concisely with plain language, "
        "grounded only in provided evidence. Do not invent fields."
    )
    user_prompt = json.dumps(
        {
            "question": question,
            "intent": intent,
            "metric": metric,
            "period": {"start_date": context.start_date, "end_date": context.end_date},
            "answer_draft": answer,
            "evidence": evidence,
            "assumptions": assumptions,
        }
    )
    llm_result = llm.generate(system_prompt, user_prompt)
    if "Returning grounded data-only summary" in llm_result.text or "LLM call failed" in llm_result.text:
        narrative = answer
        assumptions.append(llm_result.text)
    else:
        narrative = llm_result.text

    result = {
        "answer": narrative,
        "evidence": evidence,
        "period": {"start_date": context.start_date, "end_date": context.end_date},
        "assumptions": assumptions,
        "confidence": confidence,
        "meta": {
            "intent": intent,
            "metric": metric,
            "llm_provider": llm_result.provider,
            "llm_model": llm_result.used_model,
            "schema": QA_RESPONSE_SCHEMA,
        },
    }
    _write_audit(audit_log_path, question, result)
    return result


def _write_audit(audit_log_path: str | None, question: str, result: dict[str, Any]) -> None:
    if not audit_log_path:
        return
    path = Path(audit_log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {"question": question, "result": result}
    if path.exists():
        existing = path.read_text(encoding="utf-8")
    else:
        existing = ""
    path.write_text(existing + json.dumps(event) + "\n", encoding="utf-8")
