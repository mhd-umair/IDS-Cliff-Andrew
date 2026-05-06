from __future__ import annotations

import sqlite3

import pandas as pd

from src.db import run_query

POSTED_STATUSES = ("finalized", "archived")


def owner_metrics(conn: sqlite3.Connection, start_date: str, end_date: str, monthly_overhead_target: float) -> dict:
    sql = """
    SELECT
      ROUND(SUM(COALESCE(ih.TotalInvoice,0)),2) AS total_revenue,
      ROUND(SUM(COALESCE(seg.NetExt,0)),2) AS service_revenue,
      ROUND(SUM(COALESCE(sp.NetExt,0)),2) AS parts_revenue,
      ROUND(SUM(COALESCE(sp.NetExt,0) - (COALESCE(sp.AvgCost,0) * COALESCE(sp.Qty,0))),2) AS parts_gp,
      ROUND(SUM(COALESCE(su.NetExt,0) - (COALESCE(su.InvoiceCost,0) * COALESCE(su.Qty,0))),2) AS unit_gp
    FROM InvoiceHeader ih
    LEFT JOIN InvoiceSegment seg ON seg.InvDocId = ih.InvoiceDocId
    LEFT JOIN InvoiceDetail id ON id.InvoiceDocId = ih.InvoiceDocId
    LEFT JOIN SalePart sp ON sp.ItemId = id.ItemId
    LEFT JOIN SaleUnit su ON su.ItemId = id.ItemId
    WHERE date(ih.ActivityDate) BETWEEN date(?) AND date(?)
      AND ih.Status IN (?,?)
    """
    row = run_query(conn, sql, (start_date, end_date, *POSTED_STATUSES)).iloc[0]
    service_gp = float(row["service_revenue"] or 0) * 0.55
    parts_gp = float(row["parts_gp"] or 0)
    absorption = ((service_gp + parts_gp) / monthly_overhead_target * 100) if monthly_overhead_target else 0.0
    return {
        "total_revenue": float(row["total_revenue"] or 0),
        "service_revenue": float(row["service_revenue"] or 0),
        "parts_revenue": float(row["parts_revenue"] or 0),
        "parts_gp": parts_gp,
        "unit_gp": float(row["unit_gp"] or 0),
        "service_absorption_proxy_pct": absorption,
    }


def service_metrics(conn: sqlite3.Connection, start_date: str, end_date: str) -> dict:
    kpi_sql = """
    SELECT
      COUNT(DISTINCT CASE WHEN ih.InvoiceType='wo' AND ih.Status NOT IN ('finalized','archived','voided') THEN ih.InvoiceDocId END) AS open_work_orders,
      COUNT(DISTINCT CASE WHEN ih.InvoiceType='wo' AND ih.Status NOT IN ('finalized','archived','voided')
        AND julianday('now') - julianday(date(ih.ActivityDate)) > 14 THEN ih.InvoiceDocId END) AS wo_14_plus
    FROM InvoiceHeader ih
    WHERE date(ih.ActivityDate) BETWEEN date(?) AND date(?)
    """
    kpi = run_query(conn, kpi_sql, (start_date, end_date)).iloc[0]

    efficiency_sql = """
    SELECT
      strftime('%Y-%W', TimeOn) AS week,
      ROUND(SUM(COALESCE(ElapsedHours,0)),2) AS billed_hours,
      COUNT(DISTINCT TechId) AS active_techs,
      ROUND((SUM(COALESCE(ElapsedHours,0)) / NULLIF(COUNT(DISTINCT TechId)*40,0))*100,2) AS efficiency_pct
    FROM WorkInProgress
    WHERE date(TimeOn) BETWEEN date(?) AND date(?)
    GROUP BY strftime('%Y-%W', TimeOn)
    ORDER BY week
    """
    eff = run_query(conn, efficiency_sql, (start_date, end_date))
    latest_eff = float(eff.iloc[-1]["efficiency_pct"]) if not eff.empty else 0.0
    return {
        "open_work_orders": int(kpi["open_work_orders"] or 0),
        "open_work_orders_14_plus": int(kpi["wo_14_plus"] or 0),
        "technician_efficiency_pct": latest_eff,
        "weekly_efficiency": eff,
    }


def parts_metrics(conn: sqlite3.Connection, start_date: str, end_date: str) -> dict:
    turn_sql = """
    SELECT
      ROUND(SUM(COALESCE(sp.AvgCost,0) * COALESCE(sp.Qty,0)),2) AS parts_sales_cost
    FROM SalePart sp
    JOIN InvoiceDetail id ON id.ItemId = sp.ItemId
    JOIN InvoiceHeader ih ON ih.InvoiceDocId = id.InvoiceDocId
    WHERE date(ih.ActivityDate) BETWEEN date(?) AND date(?)
      AND ih.Status IN (?,?)
    """
    part_sales_cost = float(run_query(conn, turn_sql, (start_date, end_date, *POSTED_STATUSES)).iloc[0]["parts_sales_cost"] or 0)

    inv_sql = """
    WITH avg_cost AS (
      SELECT PartId, AVG(COALESCE(AvgCost,0)) AS avg_cost
      FROM SalePart
      GROUP BY PartId
    )
    SELECT
      ROUND(SUM(((COALESCE(pl.MinStock,0) + COALESCE(pl.MaxStock,0)) / 2.0) * COALESCE(ac.avg_cost,0)),2) AS avg_inventory_proxy
    FROM PartLocation pl
    LEFT JOIN avg_cost ac ON ac.PartId = pl.PartId
    WHERE COALESCE(pl.IsActive,1)=1
    """
    avg_inventory_proxy = float(run_query(conn, inv_sql).iloc[0]["avg_inventory_proxy"] or 0)
    turns = (part_sales_cost / avg_inventory_proxy) if avg_inventory_proxy else 0.0

    dead_sql = """
    WITH sold AS (
      SELECT DISTINCT sp.PartId
      FROM SalePart sp
      JOIN InvoiceDetail id ON id.ItemId = sp.ItemId
      JOIN InvoiceHeader ih ON ih.InvoiceDocId = id.InvoiceDocId
      WHERE date(ih.ActivityDate) >= date('now','-18 month')
        AND ih.Status IN ('finalized','archived')
    )
    SELECT
      COUNT(*) AS active_parts,
      SUM(CASE WHEN s.PartId IS NULL THEN 1 ELSE 0 END) AS dead_parts
    FROM PartMaster pm
    LEFT JOIN sold s ON s.PartId = pm.PartId
    WHERE COALESCE(pm.IsActive,1)=1
    """
    dead = run_query(conn, dead_sql).iloc[0]
    active_parts = int(dead["active_parts"] or 0)
    dead_parts = int(dead["dead_parts"] or 0)
    dead_ratio = (dead_parts / active_parts * 100) if active_parts else 0.0
    return {
        "parts_turn_r12": turns,
        "dead_stock_ratio_pct": dead_ratio,
        "dead_parts": dead_parts,
        "active_parts": active_parts,
    }


def monthly_trends(conn: sqlite3.Connection, start_date: str, end_date: str) -> pd.DataFrame:
    sql = """
    SELECT
      strftime('%Y-%m', ActivityDate) AS month,
      ROUND(SUM(COALESCE(TotalInvoice,0)),2) AS revenue
    FROM InvoiceHeader
    WHERE date(ActivityDate) BETWEEN date(?) AND date(?)
      AND Status IN (?,?)
    GROUP BY strftime('%Y-%m', ActivityDate)
    ORDER BY month
    """
    return run_query(conn, sql, (start_date, end_date, *POSTED_STATUSES))
