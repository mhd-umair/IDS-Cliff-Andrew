from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st


@st.cache_resource
def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def run_query(conn: sqlite3.Connection, sql: str, params: tuple | None = None) -> pd.DataFrame:
    if params is None:
        params = ()
    return pd.read_sql_query(sql, conn, params=params)


def default_db_path() -> str:
    root = Path(__file__).resolve().parents[1]
    return str(root / "perseus_equipment_database.db")
