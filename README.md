# Perseus Equipment AI Hackathon

Welcome to the Perseus Equipment AI Hackathon. Your challenge is to turn a real-world style dealership operations database into an intelligent analytics platform that helps business users understand customers, sales, service work, and inventory health.

The database for this challenge is `perseus_equipment_database.db`, a SQLite database in the root of this workspace.

## Company Story

Perseus Equipment is a fictional regional equipment dealership serving contractors, landscapers, municipalities, farmers across the Midwest.

The company sells compact construction equipment, replacement parts, attachments, and service work. Over years of growth, Perseus collected a large amount of operational data in its dealer management system, but managers still rely on manual reports, spreadsheets, and tribal knowledge to answer basic questions:

- Which customers are growing, slowing down, or at risk?
- What parts and equipment categories drive the most revenue?
- How healthy is inventory?
- What service work is moving through the shop?
- Where should sales, service, and inventory teams focus next?

Your job is to build an analytics platform that makes this data easier to explore and act on.

All customer names and customer numbers in the shared database have been anonymized with random company-style names and random customer numbers. Treat the data as sensitive anyway and avoid exposing raw credentials, passwords, hashes, or internal-only fields in your application.

## Challenge Goal

Build an analytics dashboard application that helps Perseus Equipment understand how the business is performing.

Your platform should combine:

- Clear executive KPIs.
- Charts and graphs.
- Drill-down workflows.
- Customer, inventory, sales, and service insights.

## Database Overview

The database is SQLite and contains dealer operations data across customers, invoices, parts, units,  payments, service work, locations, and lookup tables.

Important notes:

- Dates are stored mostly as `TEXT` values in timestamp-like formats.
- Monetary and quantity values are stored mostly as `NUMERIC`.
- Many tables include `IsActive`, `EntDate`, `ModDate`, `EntBy`, and `ModBy`.
- Customer names and numbers can appear both in master tables and denormalized transaction tables.
- Invoice records are central to many analytics workflows.
- Useful invoice statuses include `finalized`, `archived`, `voided`, `quote`, `committed`, and `draft`.
- For revenue analytics, prefer posted invoice statuses such as `finalized` and `archived`.

## Key Business Areas

### Customers

Use these tables for customer analytics:

- `Customer`: customer master records, including `CustomerId`, `CustomerNo`, `CustomerName`, active flag, credit fields, and location references.
- `Contact`: people linked to customers.
- `CustomerEmail`: email addresses linked to contacts.
- `CustomerPhone`: phone numbers linked to contacts.
- `CustomerAddress`: customer mailing and shipping addresses.
- `CustomerClass` and `CustomerClassType`: customer classification data.

Suggested customer insights:

- Top customers by revenue.
- Customer invoice count and average invoice value.
- Last purchase date.
- Customer activity trends over time.
- Customers with declining activity.
- Customers without recent purchases.
- Contact completeness: missing email or phone.
- Drill down from customer summary to invoices, purchased parts, and contact records.

### Sales and Invoices

Use these tables for invoice and sales analytics:

- `InvoiceHeader`: invoice-level facts such as `InvoiceDocId`, `InvoiceNo`, `Status`, `InvoiceType`, `ActivityDate`, `CustomerId`, `CustomerName`, `CustomerNo`, `SalesPersonName`, and `TotalInvoice`.
- `InvoiceDetail`: invoice line items, quantities, prices, discounts, net extension, and item type.
- `InvoiceMiscellaneousCharge`: miscellaneous invoice charges.
- `InvoiceSegment`: work order/service segments attached to invoices.
- `SalesTax`: taxable amounts, non-taxable amounts, and tax jurisdiction data.

Common invoice types:

- `in`: standard invoice.
- `wo`: work order invoice.
- `rl`: rental invoice.

Suggested sales insights:

- Revenue by month.
- Revenue by invoice type.
- Invoice count by status.
- Average invoice value.
- Top customers.
- Top salespeople, if populated.
- Taxable versus non-taxable sales.
- Drill down from chart segments to invoice rows.

### Parts Inventory and Parts Sales

Use these tables for parts analytics:

- `PartMaster`: part master catalog with `PartId`, `MfgId`, `PartStatus`, `PartType`, `PartNo`, `Description`, and active flag.
- `PartLocation`: location-level part settings such as bins, min stock, max stock, count schedules, and stocking rules.
- `PartManufacturer`: manufacturer lookup.
- `PartGroup`: part group lookup.
- `PartProductLine`: product line lookup.
- `SalePart`: sold parts linked to invoice detail through `ItemId`, including `PartId`, `PartNo`, `Qty`, `UnitPrice`, `NetExt`, `AvgCost`, and manufacturer code.

Suggested parts insights:

- Top selling parts by revenue.
- Top selling parts by quantity.
- Parts sales velocity over time.
- Part sales margin estimates using `NetExt` and `AvgCost` where available.
- Parts by manufacturer.
- Parts with configured min/max stock.
- Parts without useful stocking policy.
- Drill down from a part to invoices where it was sold.

Note: this dataset exposes useful parts catalog and sales data, but may not expose a simple current on-hand quantity column. Be careful with assumptions. If you calculate inventory health, explain what fields you used.

### Equipment and Unit Inventory

Use these tables for whole-good equipment and unit analytics:

- `UnitBase`: equipment/unit master records, including `UnitId`, `StockNo`, `UnitCategoryId`, `UnitConditionId`, `Make`, `Model`, `Year`, `StockStatus`, `BaseRetail`, `BaseCost`.
- `UnitCategory`: unit category lookup.
- `UnitCondition`: condition lookup.
- `UnitMake`: make lookup.
- `UnitSerial`: serial and warranty information.
- `UnitCustomer`: customer/unit history with invoice amount, trade amount, list amount, configured cost, source, and event date.
- `SaleUnit`: unit sale details.
- `SaleUnitTradeIn`: trade-in details.

Suggested unit inventory insights:

- Units by stock status.
- In-stock retail value.
- Unit cost versus retail.
- Unit aging using `DateReceived`.
- New versus used inventory.
- Inventory by category.
- Trade-in activity.
- Drill down from stock status to unit detail.

### Service and Work Orders

Use these tables for service analytics:

- `InvoiceHeader`: work order fields such as work order status, technician, pickup/delivery dates, estimates, unit details, and meter data.
- `InvoiceSegment`: service segments with labor, shop supplies, service code, segment status, and unit details.
- `WorkInProgress`: technician time entries, elapsed hours, comments, and transfer links.
- `WorkOrderSchedule`: required, scheduled, and actual service schedule timestamps.
- `SettingsWorkOrderStatus`: status lookup.
- `AppUser`: users and technicians.

Suggested service insights:

- Open work orders by status.
- Technician workload.
- Labor hours by technician.
- Estimate versus actual revenue.
- Work order aging.
- Schedule adherence.
- Drill down from work order status to invoice/service segment detail.

### Payments

Use these tables for payment analytics:

- `Payment`: payment records with method, amount, authorization, invoice reference, and entered date.
- `PaymentMethod`: payment method lookup.
- `PaymentReceivablesDetail`: receivable detail linked to bill-to customer information.

Suggested payment insights:

- Payments by method.
- Payment activity over time.
- Receivables customer coverage.
- Payment amount by customer.

## Minimum Product Requirements

Your analytics platform should include at least:

- A landing dashboard with executive KPIs.
- Sales trend chart over time.
- Customer leaderboard.
- Inventory or parts health section.
- Drill-down capability from summaries into detail rows.
- Search or filtering for customers and invoices.
- Clear labels explaining what each metric means.
- A polished UI suitable for business users.

## Recommended Drill-Down Flows

Strong submissions should let a user move from summary to detail without losing context.

Recommended flows:

- Revenue KPI to invoice list.
- Monthly revenue chart to invoices for that month.
- Top customer list to customer profile.
- Customer profile to recent invoices.
- Customer profile to purchased parts.
- Inventory stock status chart to unit detail.
- Top part chart to part detail and related invoices.
- Service status chart to open work orders or service segments.

## UI Expectations

Build for a dealership manager, not a database engineer.

Good UI characteristics:

- Clear navigation.
- Responsive layout.
- KPI cards with concise labels.
- Charts that support filtering or drill-down.
- Detail tables with sorting or search.
- Links between related records.
- Helpful empty states.
- Plain-English explanations.
- Visual hierarchy for urgent or important metrics.

Bootstrap, MudBlazor, Radzen, or another polished UI framework are all acceptable.

## Deliverables

Each team should be ready to demo:

- The running analytics application.
- The main dashboard.
- At least two drill-down flows.
- One customer insight.

## Getting Started

Suggested first steps:

1. Inspect the SQLite schema.
2. Identify the questions your dashboard should answer.
3. Build a small data access layer with read-only queries.
4. Start with a few KPIs and one chart.
5. Add drill-down pages.
6. Add AI summaries or question answering.
7. Polish the experience for a business demo.

Have fun building something that helps Perseus Equipment make faster, smarter decisions.
