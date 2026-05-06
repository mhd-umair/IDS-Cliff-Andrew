from __future__ import annotations

import sqlite3

import pandas as pd

from src.db import run_query


POSTED_STATUSES = ("finalized", "archived")


def get_filter_options(conn: sqlite3.Connection) -> dict[str, list[str]]:
    invoice_types = run_query(
        conn,
        "SELECT DISTINCT InvoiceType FROM InvoiceHeader WHERE InvoiceType IS NOT NULL ORDER BY InvoiceType",
    )["InvoiceType"].tolist()
    statuses = run_query(
        conn,
        "SELECT DISTINCT Status FROM InvoiceHeader WHERE Status IS NOT NULL ORDER BY Status",
    )["Status"].tolist()
    sales_people = run_query(
        conn,
        "SELECT DISTINCT SalesPersonName FROM InvoiceHeader WHERE SalesPersonName IS NOT NULL AND SalesPersonName <> '' ORDER BY SalesPersonName",
    )["SalesPersonName"].tolist()
    return {
        "invoice_types": invoice_types,
        "statuses": statuses,
        "sales_people": sales_people,
    }


def get_date_bounds(conn: sqlite3.Connection) -> tuple[pd.Timestamp, pd.Timestamp]:
    df = run_query(
        conn,
        "SELECT MIN(date(ActivityDate)) AS min_date, MAX(date(ActivityDate)) AS max_date FROM InvoiceHeader",
    )
    return pd.to_datetime(df.iloc[0]["min_date"]), pd.to_datetime(df.iloc[0]["max_date"])


def _invoice_filter_where(filters: dict, include_statuses: bool = True) -> tuple[str, list]:
    clauses = ["1=1"]
    params: list = []

    clauses.append("date(ActivityDate) BETWEEN date(?) AND date(?)")
    params.extend([filters["start_date"], filters["end_date"]])

    if filters["invoice_types"]:
        placeholders = ",".join(["?"] * len(filters["invoice_types"]))
        clauses.append(f"InvoiceType IN ({placeholders})")
        params.extend(filters["invoice_types"])

    if include_statuses and filters["statuses"]:
        placeholders = ",".join(["?"] * len(filters["statuses"]))
        clauses.append(f"Status IN ({placeholders})")
        params.extend(filters["statuses"])

    if filters["sales_people"]:
        placeholders = ",".join(["?"] * len(filters["sales_people"]))
        clauses.append(f"SalesPersonName IN ({placeholders})")
        params.extend(filters["sales_people"])

    where_clause = " AND ".join(clauses)
    return where_clause, params


def get_executive_kpis(conn: sqlite3.Connection, filters: dict) -> dict[str, float]:
    where, params = _invoice_filter_where(filters)
    where_no_status, params_no_status = _invoice_filter_where(filters, include_statuses=False)
    posted_placeholders = ",".join(["?"] * len(POSTED_STATUSES))
    sql = f"""
    SELECT
      ROUND(SUM(CASE WHEN Status IN ({posted_placeholders}) THEN COALESCE(TotalInvoice, 0) ELSE 0 END), 2) AS posted_revenue,
      ROUND(AVG(CASE WHEN Status IN ({posted_placeholders}) THEN COALESCE(TotalInvoice, 0) END), 2) AS avg_invoice_value,
      COUNT(DISTINCT CASE WHEN Status IN ({posted_placeholders}) THEN CustomerId END) AS active_customers,
      (
        SELECT COUNT(1)
        FROM InvoiceHeader ow
        WHERE {where_no_status}
          AND ow.InvoiceType='wo'
          AND ow.Status NOT IN ({posted_placeholders}, 'voided')
      ) AS open_work_orders
    FROM InvoiceHeader
    WHERE {where}
    """
    final_params = (
        list(POSTED_STATUSES)
        + list(POSTED_STATUSES)
        + list(POSTED_STATUSES)
        + params_no_status
        + list(POSTED_STATUSES)
        + params
    )
    df = run_query(conn, sql, tuple(final_params))
    row = df.iloc[0].to_dict()
    return {
        "posted_revenue": float(row["posted_revenue"] or 0),
        "avg_invoice_value": float(row["avg_invoice_value"] or 0),
        "active_customers": float(row["active_customers"] or 0),
        "open_work_orders": float(row["open_work_orders"] or 0),
    }


def get_monthly_revenue(conn: sqlite3.Connection, filters: dict) -> pd.DataFrame:
    where, params = _invoice_filter_where(filters)
    placeholders = ",".join(["?"] * len(POSTED_STATUSES))
    sql = f"""
    SELECT
      strftime('%Y-%m', ActivityDate) AS month,
      ROUND(SUM(COALESCE(TotalInvoice, 0)), 2) AS revenue
    FROM InvoiceHeader
    WHERE {where}
      AND Status IN ({placeholders})
    GROUP BY strftime('%Y-%m', ActivityDate)
    ORDER BY month
    """
    return run_query(conn, sql, tuple(params + list(POSTED_STATUSES)))


def get_customer_leaderboard(conn: sqlite3.Connection, filters: dict, limit: int = 50) -> pd.DataFrame:
    where, params = _invoice_filter_where(filters)
    placeholders = ",".join(["?"] * len(POSTED_STATUSES))
    sql = f"""
    SELECT
      CustomerId,
      CustomerName,
      CustomerNo,
      COUNT(1) AS invoice_count,
      ROUND(SUM(COALESCE(TotalInvoice, 0)), 2) AS revenue,
      MAX(ActivityDate) AS last_purchase_date
    FROM InvoiceHeader
    WHERE {where}
      AND Status IN ({placeholders})
    GROUP BY CustomerId, CustomerName, CustomerNo
    ORDER BY revenue DESC
    LIMIT {int(limit)}
    """
    return run_query(conn, sql, tuple(params + list(POSTED_STATUSES)))


def get_invoice_detail_list(conn: sqlite3.Connection, filters: dict, limit: int = 200) -> pd.DataFrame:
    where, params = _invoice_filter_where(filters)
    sql = f"""
    SELECT
      InvoiceDocId,
      InvoiceNo,
      InvoiceType,
      Status,
      ActivityDate,
      CustomerName,
      CustomerNo,
      SalesPersonName,
      ROUND(COALESCE(TotalInvoice, 0), 2) AS TotalInvoice
    FROM InvoiceHeader
    WHERE {where}
    ORDER BY date(ActivityDate) DESC
    LIMIT {int(limit)}
    """
    return run_query(conn, sql, tuple(params))


def get_parts_health(conn: sqlite3.Connection, filters: dict, limit: int = 100) -> pd.DataFrame:
    where, params = _invoice_filter_where(filters)
    placeholders = ",".join(["?"] * len(POSTED_STATUSES))
    sql = f"""
    SELECT
      sp.PartId,
      sp.PartNo,
      ROUND(SUM(COALESCE(sp.Qty, 0)), 2) AS qty_sold,
      ROUND(SUM(COALESCE(sp.NetExt, 0)), 2) AS part_revenue,
      ROUND(SUM(COALESCE(sp.AvgCost, 0) * COALESCE(sp.Qty, 0)), 2) AS est_cost,
      ROUND(SUM(COALESCE(sp.NetExt, 0)) - SUM(COALESCE(sp.AvgCost, 0) * COALESCE(sp.Qty, 0)), 2) AS est_margin
    FROM SalePart sp
    JOIN InvoiceDetail id ON id.ItemId = sp.ItemId
    JOIN InvoiceHeader ih ON ih.InvoiceDocId = id.InvoiceDocId
    WHERE {where}
      AND ih.Status IN ({placeholders})
    GROUP BY sp.PartId, sp.PartNo
    ORDER BY part_revenue DESC
    LIMIT {int(limit)}
    """
    return run_query(conn, sql, tuple(params + list(POSTED_STATUSES)))


def get_service_status(conn: sqlite3.Connection, filters: dict) -> pd.DataFrame:
    where, params = _invoice_filter_where(filters)
    sql = f"""
    SELECT
      Status,
      COUNT(1) AS work_order_count
    FROM InvoiceHeader
    WHERE {where}
      AND InvoiceType = 'wo'
    GROUP BY Status
    ORDER BY work_order_count DESC
    """
    return run_query(conn, sql, tuple(params))


def get_customer_profile(conn: sqlite3.Connection, customer_id: int, filters: dict) -> dict[str, pd.DataFrame]:
    where, params = _invoice_filter_where(filters)
    customer_sql = """
    SELECT CustomerId, CustomerNo, CustomerName, IsActive, EntDate, ModDate
    FROM Customer
    WHERE CustomerId = ?
    """
    customer = run_query(conn, customer_sql, (customer_id,))

    inv_sql = f"""
    SELECT InvoiceDocId, InvoiceNo, ActivityDate, Status, InvoiceType, ROUND(COALESCE(TotalInvoice,0),2) AS TotalInvoice
    FROM InvoiceHeader
    WHERE CustomerId = ? AND {where}
    ORDER BY date(ActivityDate) DESC
    LIMIT 100
    """
    invoices = run_query(conn, inv_sql, tuple([customer_id] + params))

    parts_sql = f"""
    SELECT sp.PartNo, ROUND(SUM(COALESCE(sp.Qty,0)),2) AS qty, ROUND(SUM(COALESCE(sp.NetExt,0)),2) AS revenue
    FROM InvoiceHeader ih
    JOIN InvoiceDetail id ON id.InvoiceDocId = ih.InvoiceDocId
    JOIN SalePart sp ON sp.ItemId = id.ItemId
    WHERE ih.CustomerId = ? AND {where}
    GROUP BY sp.PartNo
    ORDER BY revenue DESC
    LIMIT 25
    """
    parts = run_query(conn, parts_sql, tuple([customer_id] + params))
    return {"customer": customer, "invoices": invoices, "parts": parts}
