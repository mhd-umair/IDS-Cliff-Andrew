from __future__ import annotations

import sqlite3

import pandas as pd

from src.db import run_query

QUESTION_MONEY = "Where am I leaving money on the table?"
QUESTION_UNIT = "How do I make more from every unit I sell?"
QUESTION_REPEAT = "How do I get more repeat business?"
QUESTION_OPS = "What's slowing down revenue in my operations?"

OWNER_QUESTIONS = [QUESTION_MONEY, QUESTION_UNIT, QUESTION_REPEAT, QUESTION_OPS]


def build_opportunity_board(conn: sqlite3.Connection, filters: dict) -> pd.DataFrame:
    start_date = filters["start_date"]
    end_date = filters["end_date"]

    opportunities: list[dict] = []
    opportunities.extend(_churn_risk(conn, start_date, end_date))
    opportunities.extend(_attachment_play(conn, start_date, end_date))
    opportunities.extend(_workflow_play(conn, start_date, end_date))
    opportunities.extend(_quote_lag_play(conn, start_date, end_date))

    if not opportunities:
        return pd.DataFrame(
            columns=[
                "objective",
                "question",
                "play_name",
                "entity_type",
                "entity_id",
                "entity_label",
                "estimated_upside",
                "confidence",
                "score",
                "why",
                "action",
            ]
        )

    df = pd.DataFrame(opportunities)
    df["score"] = (df["estimated_upside"] * (df["confidence"] / 100.0)).round(2)
    return df.sort_values(["score", "estimated_upside"], ascending=False).reset_index(drop=True)


def build_owner_question_context(conn: sqlite3.Connection, filters: dict) -> dict:
    board = build_opportunity_board(conn, filters)
    diagnostics = _build_question_diagnostics(conn, filters, board)
    return {"board": board, "diagnostics": diagnostics}


def _build_question_diagnostics(conn: sqlite3.Connection, filters: dict, board: pd.DataFrame) -> dict[str, dict]:
    start_date = filters["start_date"]
    end_date = filters["end_date"]

    money_candidates = int(
        run_query(
            conn,
            """
            SELECT COUNT(1) AS cnt
            FROM QuoteDetails q
            JOIN InvoiceHeader ih ON ih.InvoiceDocId = q.InvoiceDocId
            WHERE q.SalesContractDate IS NOT NULL
              AND q.InvoiceFinalizedDate IS NOT NULL
              AND date(ih.ActivityDate) BETWEEN date(?) AND date(?)
            """,
            (start_date, end_date),
        ).iloc[0]["cnt"]
    )

    unit_candidates = int(
        run_query(
            conn,
            """
            SELECT COUNT(1) AS cnt
            FROM InvoiceHeader ih
            WHERE ih.Status IN ('finalized','archived')
              AND ih.InvoiceType = 'in'
              AND date(ih.ActivityDate) BETWEEN date(?) AND date(?)
              AND EXISTS (
                SELECT 1 FROM InvoiceDetail id
                JOIN SaleUnit su ON su.ItemId = id.ItemId
                WHERE id.InvoiceDocId = ih.InvoiceDocId
              )
            """,
            (start_date, end_date),
        ).iloc[0]["cnt"]
    )

    repeat_candidates = int(
        run_query(
            conn,
            """
            SELECT COUNT(DISTINCT CustomerId) AS cnt
            FROM InvoiceHeader
            WHERE Status IN ('finalized','archived')
              AND date(ActivityDate) BETWEEN date(?) AND date(?)
            """,
            (start_date, end_date),
        ).iloc[0]["cnt"]
    )

    ops_candidates = int(
        run_query(
            conn,
            """
            SELECT COUNT(1) AS cnt
            FROM InvoiceHeader ih
            WHERE ih.InvoiceType = 'wo'
              AND ih.Status NOT IN ('finalized','archived','voided')
              AND date(ih.ActivityDate) BETWEEN date(?) AND date(?)
            """,
            (start_date, end_date),
        ).iloc[0]["cnt"]
    )

    counts = {q: 0 for q in OWNER_QUESTIONS}
    if not board.empty:
        question_counts = board.groupby("question").size().to_dict()
        counts.update({k: int(v) for k, v in question_counts.items()})

    def diag(question: str, rule_name: str, required_fields: str, candidates: int) -> dict:
        eligible = int(counts.get(question, 0))
        if eligible > 0:
            state = "insights_available"
        elif candidates == 0:
            state = "data_gap"
        else:
            state = "filter_or_threshold"
        return {
            "state": state,
            "rule_name": rule_name,
            "required_fields": required_fields,
            "candidates_scanned": candidates,
            "rows_passing_threshold": eligible,
            "opportunity_count": eligible,
        }

    return {
        QUESTION_MONEY: diag(
            QUESTION_MONEY,
            "Quote-to-finalized lag play",
            "QuoteDetails.SalesContractDate, QuoteDetails.InvoiceFinalizedDate",
            money_candidates,
        ),
        QUESTION_UNIT: diag(
            QUESTION_UNIT,
            "Attachment rate play",
            "InvoiceHeader + InvoiceDetail + SaleUnit + SalePart",
            unit_candidates,
        ),
        QUESTION_REPEAT: diag(
            QUESTION_REPEAT,
            "Churn risk play",
            "InvoiceHeader.CustomerId, InvoiceHeader.ActivityDate, InvoiceHeader.TotalInvoice",
            repeat_candidates,
        ),
        QUESTION_OPS: diag(
            QUESTION_OPS,
            "Workflow acceleration play",
            "InvoiceHeader.InvoiceType, InvoiceHeader.Status, InvoiceHeader.ActivityDate",
            ops_candidates,
        ),
    }


def _churn_risk(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    sql = """
    WITH recent AS (
      SELECT CustomerId, CustomerName, CustomerNo, SUM(COALESCE(TotalInvoice,0)) AS rev_recent, MAX(date(ActivityDate)) AS last_date
      FROM InvoiceHeader
      WHERE Status IN ('finalized','archived')
        AND date(ActivityDate) BETWEEN date(?) AND date(?)
      GROUP BY CustomerId, CustomerName, CustomerNo
    ),
    prior AS (
      SELECT CustomerId, SUM(COALESCE(TotalInvoice,0)) AS rev_prior
      FROM InvoiceHeader
      WHERE Status IN ('finalized','archived')
        AND date(ActivityDate) >= date(?, '-365 day')
        AND date(ActivityDate) < date(?)
      GROUP BY CustomerId
    )
    SELECT r.CustomerId, r.CustomerName, r.CustomerNo, r.rev_recent, COALESCE(p.rev_prior,0) AS rev_prior, r.last_date
    FROM recent r
    LEFT JOIN prior p ON p.CustomerId = r.CustomerId
    WHERE COALESCE(p.rev_prior,0) > r.rev_recent * 1.2
    ORDER BY (COALESCE(p.rev_prior,0) - r.rev_recent) DESC
    LIMIT 30
    """
    df = run_query(conn, sql, (start_date, end_date, start_date, start_date))
    plays = []
    for _, row in df.iterrows():
        drop = max(float(row["rev_prior"]) - float(row["rev_recent"]), 0.0)
        plays.append(
            {
                "objective": "Increase recurring revenue",
                "question": QUESTION_REPEAT,
                "play_name": "Churn risk play",
                "entity_type": "customer",
                "entity_id": int(row["CustomerId"]),
                "entity_label": f"{row['CustomerName']} ({row['CustomerNo']})",
                "estimated_upside": round(drop * 0.25, 2),
                "confidence": 75,
                "why": "Customer spend declined versus prior year period.",
                "action": "Call account with a service + parts check-in offer this week.",
            }
        )
    return plays


def _attachment_play(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    sql = """
    WITH unit_invoices AS (
      SELECT ih.InvoiceDocId, ih.CustomerId, ih.CustomerName, ih.CustomerNo, COALESCE(ih.TotalInvoice,0) AS total
      FROM InvoiceHeader ih
      WHERE ih.Status IN ('finalized','archived')
        AND ih.InvoiceType = 'in'
        AND date(ih.ActivityDate) BETWEEN date(?) AND date(?)
        AND EXISTS (
          SELECT 1 FROM InvoiceDetail id
          JOIN SaleUnit su ON su.ItemId = id.ItemId
          WHERE id.InvoiceDocId = ih.InvoiceDocId
        )
    ),
    part_attach AS (
      SELECT id.InvoiceDocId, SUM(COALESCE(sp.NetExt,0)) AS part_revenue
      FROM InvoiceDetail id
      JOIN SalePart sp ON sp.ItemId = id.ItemId
      GROUP BY id.InvoiceDocId
    )
    SELECT ui.CustomerId, ui.CustomerName, ui.CustomerNo,
           COUNT(*) AS unit_invoice_count,
           AVG(COALESCE(pa.part_revenue,0)) AS avg_part_attach
    FROM unit_invoices ui
    LEFT JOIN part_attach pa ON pa.InvoiceDocId = ui.InvoiceDocId
    GROUP BY ui.CustomerId, ui.CustomerName, ui.CustomerNo
    HAVING COUNT(*) >= 3
    ORDER BY avg_part_attach ASC
    LIMIT 25
    """
    df = run_query(conn, sql, (start_date, end_date))
    plays = []
    for _, row in df.iterrows():
        if float(row["avg_part_attach"]) > 300:
            continue
        upside = max((300 - float(row["avg_part_attach"])) * float(row["unit_invoice_count"]) * 0.5, 0.0)
        plays.append(
            {
                "objective": "Increase revenue per transaction",
                "question": QUESTION_UNIT,
                "play_name": "Attachment rate play",
                "entity_type": "customer",
                "entity_id": int(row["CustomerId"]),
                "entity_label": f"{row['CustomerName']} ({row['CustomerNo']})",
                "estimated_upside": round(upside, 2),
                "confidence": 70,
                "why": "Unit deals show low average parts attachment.",
                "action": "Introduce standard unit bundle (accessories + first service package).",
            }
        )
    return plays


def _workflow_play(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    sql = """
    SELECT ih.InvoiceDocId, ih.InvoiceNo, ih.CustomerName, ih.Status,
           CAST(julianday('now') - julianday(date(ih.ActivityDate)) AS INT) AS age_days,
           COALESCE(ih.TotalInvoice,0) AS total_invoice
    FROM InvoiceHeader ih
    WHERE ih.InvoiceType = 'wo'
      AND ih.Status NOT IN ('finalized','archived','voided')
      AND date(ih.ActivityDate) BETWEEN date(?) AND date(?)
    ORDER BY age_days DESC
    LIMIT 25
    """
    df = run_query(conn, sql, (start_date, end_date))
    plays = []
    for _, row in df.iterrows():
        age_days = int(row["age_days"] or 0)
        if age_days < 14:
            continue
        delayed = float(row["total_invoice"] or 0) * min(age_days / 60.0, 1.0)
        plays.append(
            {
                "objective": "Improve operational efficiency",
                "question": QUESTION_OPS,
                "play_name": "Workflow acceleration play",
                "entity_type": "work_order",
                "entity_id": int(row["InvoiceDocId"]),
                "entity_label": f"WO {row['InvoiceNo']} ({row['CustomerName']})",
                "estimated_upside": round(delayed, 2),
                "confidence": 80,
                "why": f"Open work order is aging ({age_days} days).",
                "action": "Escalate parts/labor blockers and target closure within 72 hours.",
            }
        )
    return plays


def _quote_lag_play(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[dict]:
    sql = """
    SELECT q.InvoiceDocId, ih.InvoiceNo, ih.CustomerName, q.QuoteStatus,
           q.SalesContractDate, q.InvoiceFinalizedDate,
           CAST(julianday(date(q.InvoiceFinalizedDate)) - julianday(date(q.SalesContractDate)) AS INT) AS lag_days,
           COALESCE(ih.TotalInvoice,0) AS total_invoice
    FROM QuoteDetails q
    JOIN InvoiceHeader ih ON ih.InvoiceDocId = q.InvoiceDocId
    WHERE q.SalesContractDate IS NOT NULL
      AND q.InvoiceFinalizedDate IS NOT NULL
      AND date(ih.ActivityDate) BETWEEN date(?) AND date(?)
    ORDER BY lag_days DESC
    LIMIT 25
    """
    df = run_query(conn, sql, (start_date, end_date))
    plays = []
    for _, row in df.iterrows():
        lag_days = int(row["lag_days"] or 0)
        if lag_days < 10:
            continue
        upside = float(row["total_invoice"] or 0) * 0.03
        plays.append(
            {
                "objective": "Where am I leaving money on the table?",
                "question": QUESTION_MONEY,
                "play_name": "Quote-to-finalized lag play",
                "entity_type": "invoice",
                "entity_id": int(row["InvoiceDocId"]),
                "entity_label": f"Invoice {row['InvoiceNo']} ({row['CustomerName']})",
                "estimated_upside": round(upside, 2),
                "confidence": 60,
                "why": f"Long conversion lag ({lag_days} days) from contract to finalization.",
                "action": "Tighten quote follow-up SLA and approval handoffs.",
            }
        )
    return plays
