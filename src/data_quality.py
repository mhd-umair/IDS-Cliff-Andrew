from __future__ import annotations

import sqlite3

import pandas as pd

from src.db import run_query


def run_data_quality_checks(conn: sqlite3.Connection) -> pd.DataFrame:
    checks: list[dict] = []

    checks.append(
        {
            "check_name": "db_integrity",
            "status": "pass"
            if run_query(conn, "PRAGMA integrity_check").iloc[0, 0] == "ok"
            else "fail",
            "details": "SQLite integrity_check",
        }
    )

    checks.extend(_pk_uniqueness_checks(conn))
    checks.extend(_orphan_checks(conn))
    checks.extend(_freshness_checks(conn))
    return pd.DataFrame(checks)


def _pk_uniqueness_checks(conn: sqlite3.Connection) -> list[dict]:
    tests = [
        ("InvoiceHeader", "InvoiceDocId"),
        ("InvoiceDetail", "ItemId"),
        ("Customer", "CustomerId"),
        ("Payment", "PaymentId"),
        ("PartMaster", "PartId"),
    ]
    rows = []
    for table, col in tests:
        sql = (
            f"SELECT COUNT(*) AS duplicates FROM ("
            f"SELECT [{col}], COUNT(*) c FROM [{table}] "
            f"GROUP BY [{col}] HAVING c > 1)"
        )
        dup_count = int(run_query(conn, sql).iloc[0]["duplicates"])
        rows.append(
            {
                "check_name": f"pk_unique_{table}_{col}",
                "status": "pass" if dup_count == 0 else "fail",
                "details": f"duplicate_values={dup_count}",
            }
        )
    return rows


def _orphan_checks(conn: sqlite3.Connection) -> list[dict]:
    relations = [
        ("InvoiceDetail", "InvoiceDocId", "InvoiceHeader", "InvoiceDocId"),
        ("Payment", "InvoiceDocId", "InvoiceHeader", "InvoiceDocId"),
        ("Contact", "CustomerId", "Customer", "CustomerId"),
        ("CustomerPhone", "ContactId", "Contact", "ContactId"),
        ("CustomerEmail", "ContactId", "Contact", "ContactId"),
    ]
    rows = []
    for source_table, source_col, target_table, target_col in relations:
        sql = f"""
        SELECT COUNT(*) AS orphan_rows
        FROM [{source_table}] s
        LEFT JOIN [{target_table}] t
          ON s.[{source_col}] = t.[{target_col}]
        WHERE s.[{source_col}] IS NOT NULL
          AND t.[{target_col}] IS NULL
        """
        orphan_rows = int(run_query(conn, sql).iloc[0]["orphan_rows"])
        rows.append(
            {
                "check_name": f"orphan_{source_table}_{source_col}",
                "status": "pass" if orphan_rows == 0 else "warn",
                "details": f"orphan_rows={orphan_rows}",
            }
        )
    return rows


def _freshness_checks(conn: sqlite3.Connection) -> list[dict]:
    sql = """
    SELECT
      CAST(julianday('now') - julianday(MAX(date(ActivityDate))) AS INT) AS days_since_latest_invoice
    FROM InvoiceHeader
    """
    lag_days = int(run_query(conn, sql).iloc[0]["days_since_latest_invoice"] or 999)
    return [
        {
            "check_name": "invoice_data_freshness",
            "status": "pass" if lag_days <= 2 else ("warn" if lag_days <= 7 else "fail"),
            "details": f"days_since_latest_invoice={lag_days}",
        }
    ]
