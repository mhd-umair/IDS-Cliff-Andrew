from __future__ import annotations

from src.db import default_db_path, get_connection
from src.opportunities import build_opportunity_board
from src.queries import (
    get_customer_leaderboard,
    get_date_bounds,
    get_executive_kpis,
    get_filter_options,
    get_monthly_revenue,
)


def _default_filters(conn):
    min_date, max_date = get_date_bounds(conn)
    opts = get_filter_options(conn)
    return {
        "start_date": str(min_date.date()),
        "end_date": str(max_date.date()),
        "invoice_types": opts["invoice_types"],
        "statuses": ["finalized", "archived"],
        "sales_people": [],
    }


def test_kpis_and_trend_queries_return_data():
    conn = get_connection(default_db_path())
    filters = _default_filters(conn)
    kpis = get_executive_kpis(conn, filters)
    monthly = get_monthly_revenue(conn, filters)

    assert kpis["posted_revenue"] > 0
    assert kpis["avg_invoice_value"] > 0
    assert len(monthly) > 0


def test_customer_board_and_opportunities_return_rows():
    conn = get_connection(default_db_path())
    filters = _default_filters(conn)
    board = get_customer_leaderboard(conn, filters)
    opps = build_opportunity_board(conn, filters)

    assert len(board) > 0
    assert "CustomerName" in board.columns
    assert "play_name" in opps.columns
