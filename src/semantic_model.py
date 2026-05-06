from __future__ import annotations

import sqlite3


CURATED_VIEW_SQL = [
    """
    CREATE VIEW IF NOT EXISTS fact_invoices AS
    SELECT
      InvoiceDocId,
      InvoiceNo,
      InvoiceType,
      Status,
      date(ActivityDate) AS activity_date,
      CustomerId,
      CustomerName,
      TotalInvoice
    FROM InvoiceHeader
    """,
    """
    CREATE VIEW IF NOT EXISTS fact_invoice_lines AS
    SELECT
      id.ItemId,
      id.InvoiceDocId,
      id.ItemType,
      id.Quantity,
      id.UnitPrice,
      id.NetExt
    FROM InvoiceDetail id
    """,
    """
    CREATE VIEW IF NOT EXISTS fact_payments AS
    SELECT
      PaymentId,
      InvoiceDocId,
      PaymentMethodId,
      date(EntDate) AS payment_date,
      TotalPaymentAmount
    FROM Payment
    """,
    """
    CREATE VIEW IF NOT EXISTS dim_customer AS
    SELECT
      CustomerId,
      CustomerNo,
      CustomerName,
      IsBusiness,
      IsActive
    FROM Customer
    """,
]


def initialize_curated_views(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    for ddl in CURATED_VIEW_SQL:
        cursor.execute(ddl)
    conn.commit()
