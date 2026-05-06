from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import plotly.express as px
import streamlit as st

from src.alerts import build_digest, evaluate_threshold_alerts
from src.data_quality import run_data_quality_checks
from src.db import default_db_path, get_connection
from src.kpi_contract import DEFAULT_THRESHOLDS, KPI_CONTRACT
from src.qa_service import QAContext, answer_question
from src.reporting_queries import monthly_trends, owner_metrics, parts_metrics, service_metrics
from src.semantic_model import initialize_curated_views

GOALS_FILE = Path(__file__).resolve().parent / "dashboard_goals.json"
DEFAULT_CONFIG = {"monthly_overhead_target": 350_000.0}

st.set_page_config(page_title="Dealership KPI Command Center", page_icon="🪚🌿", layout="wide")
st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 1.4rem;
    }
    div[data-testid="stMetric"] {
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 10px 12px;
        background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }
    div[data-testid="stMetricLabel"] > div {
        font-weight: 600;
    }
    .kpi-toolbar {
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        background: #ffffff;
        padding: 0.55rem 0.8rem;
        margin-bottom: 0.6rem;
    }
    .chainsaw-loader {
        position: fixed;
        top: 0.65rem;
        right: 1rem;
        z-index: 1000;
        font-size: 1.15rem;
        background: rgba(255, 255, 255, 0.9);
        border: 1px solid #e5e7eb;
        border-radius: 999px;
        padding: 0.2rem 0.55rem;
        display: flex;
        gap: 0.25rem;
        align-items: center;
        pointer-events: none;
    }

    .chainsaw-loader .saw {
        display: inline-block;
        animation: saw-buzz 0.65s infinite ease-in-out;
    }

    @keyframes saw-buzz {
        0% { transform: translateX(0px) rotate(-6deg); }
        50% { transform: translateX(3px) rotate(4deg); }
        100% { transform: translateX(0px) rotate(-6deg); }
    }
    </style>
    <div class="chainsaw-loader" aria-hidden="true">
        <span class="saw">🪚</span><span>🌿</span><span>🚜</span>
    </div>
    """,
    unsafe_allow_html=True,
)


def load_config() -> dict[str, float]:
    if GOALS_FILE.exists():
        try:
            data = json.loads(GOALS_FILE.read_text(encoding="utf-8"))
            return {"monthly_overhead_target": float(data.get("monthly_overhead_target", DEFAULT_CONFIG["monthly_overhead_target"]))}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict[str, float]) -> None:
    GOALS_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def severity_color(severity: str) -> str:
    return {"critical": "#b91c1c", "warning": "#b45309", "ok": "#166534"}.get(severity, "#334155")


def status_badge(label: str, severity: str) -> str:
    color = severity_color(severity)
    return f"<span style='color:{color};font-weight:700'>{label}</span>"


def parse_iso_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def format_delta(value: float, suffix: str = "") -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}{suffix}"


def format_work_order_delta(current_value: int, previous_value: int) -> str:
    diff = int(current_value - previous_value)
    sign = "+" if diff >= 0 else ""
    unit = "work order" if abs(diff) == 1 else "work orders"
    return f"{sign}{diff} {unit}"


def render_qa_response(response: dict) -> None:
    st.markdown("### Answer")
    st.write(response["answer"])
    c1, c2 = st.columns(2)
    c1.metric("Confidence", str(response.get("confidence", "unknown")).title())
    c2.caption(f"Period: {response['period']['start_date']} to {response['period']['end_date']}")
    st.markdown("### Evidence")
    if response.get("evidence"):
        st.json(response["evidence"])
    else:
        st.info("No direct evidence rows returned for this question.")
    if response.get("assumptions"):
        with st.expander("Assumptions"):
            for assumption in response["assumptions"]:
                st.markdown(f"- {assumption}")


def render_data_status_banner(quality_df, min_date: str, max_date: str, start_date: str, end_date: str) -> None:
    freshness_row = quality_df[quality_df["check_name"] == "invoice_data_freshness"] if not quality_df.empty else None
    freshness_text = "unknown"
    freshness_ok = False
    if freshness_row is not None and not freshness_row.empty:
        details = str(freshness_row.iloc[0]["details"])
        freshness_text = details.replace("days_since_latest_invoice=", "")
        freshness_ok = freshness_row.iloc[0]["status"] == "pass"

    has_data = start_date <= max_date and end_date >= min_date
    if not has_data:
        st.error(
            f"Data not loaded for this range. Available data is {min_date} to {max_date}. "
            f"You selected {start_date} to {end_date}."
        )
        return

    if freshness_ok:
        st.success(
            f"Data loaded. Coverage: {min_date} to {max_date}. "
            f"Selected: {start_date} to {end_date}. Freshness lag: {freshness_text} day(s)."
        )
    else:
        st.warning(
            f"Data loaded, but may be stale. Coverage: {min_date} to {max_date}. "
            f"Selected: {start_date} to {end_date}. Freshness lag: {freshness_text} day(s)."
        )


PRESETS = {
    "Daily Ops": {"cadence": "daily", "role": "Service Manager"},
    "Weekly Manager": {"cadence": "weekly", "role": "Owner/GM"},
    "Monthly Executive": {"cadence": "monthly", "role": "Owner/GM"},
}

SAMPLE_QUESTIONS = {
    "Owner/GM": [
        "What is our service absorption right now?",
        "How did parts turns change versus previous period?",
        "Which KPI is in critical status right now?",
    ],
    "Service Manager": [
        "What is tech efficiency in this period?",
        "Are open work orders over 14 days increasing?",
        "What changed most in service KPI performance?",
    ],
    "Parts Manager": [
        "What is our dead stock ratio?",
        "How is parts turn trending versus prior period?",
        "Which inventory KPI is currently in warning?",
    ],
}

KPI_HELP = {
    "service_absorption_proxy_pct": "Service Absorption % estimates how much of monthly overhead is covered by service + parts gross profit. Higher is better because fixed ops can sustain the business even when equipment sales are softer. Delta is shown in percentage points versus the previous same-length period.",
    "technician_efficiency_pct": "Technician Efficiency % compares billed labor hours to available technician hours. Higher usually means better labor productivity. Delta is shown in percentage points versus the previous same-length period.",
    "open_work_orders_14_plus": "Open WOs >14 Days counts work orders still open after 14 days. Lower is better; high values often indicate parts, labor, or scheduling bottlenecks. Delta is shown as number of work orders versus the previous same-length period.",
    "parts_turn_r12": "Parts Turn Rate (R12 proxy) estimates how often parts inventory is sold/used over a trailing period. Higher turns generally mean healthier inventory productivity. Delta is turns versus the previous same-length period.",
    "dead_stock_ratio_pct": "Dead Stock Ratio % is the share of active parts with no sales in the trailing 18 months. Lower is better because dead stock ties up cash. Delta is shown in percentage points versus the previous same-length period.",
    "parts_gp": "Parts Gross Profit is parts revenue minus estimated parts cost.",
    "total_revenue": "Total Revenue is the posted invoice revenue in the selected date range.",
}


conn = get_connection(default_db_path())
initialize_curated_views(conn)
min_max = conn.execute("SELECT MIN(date(ActivityDate)), MAX(date(ActivityDate)) FROM InvoiceHeader").fetchone()
min_date, max_date = min_max[0], min_max[1]
cfg = load_config()

st.title("Dealership KPI Command Center")
st.caption("Role-based reporting for Owner, Service, and Parts teams with daily/weekly/monthly cadence.")

with st.sidebar:
    st.header("Filters")
    preset = st.radio("Quick Preset", ["Custom", "Daily Ops", "Weekly Manager", "Monthly Executive"], index=0)
    today = date.today()
    data_min = date.fromisoformat(min_date)
    data_max = date.fromisoformat(max_date)
    range_mode = st.selectbox(
        "Date Range",
        ["Last 7 days", "Last 30 days", "Last 90 days", "Year to date", "Last 12 months", "Full history", "Custom"],
        index=2,
    )
    if range_mode == "Last 7 days":
        start_d, end_d = today - timedelta(days=6), today
    elif range_mode == "Last 30 days":
        start_d, end_d = today - timedelta(days=29), today
    elif range_mode == "Last 90 days":
        start_d, end_d = today - timedelta(days=89), today
    elif range_mode == "Year to date":
        start_d, end_d = date(today.year, 1, 1), today
    elif range_mode == "Last 12 months":
        start_d, end_d = today - timedelta(days=365), today
    elif range_mode == "Full history":
        start_d, end_d = data_min, data_max
    else:
        dr = st.date_input("Custom range", value=(data_min, data_max))
        if len(dr) == 2:
            start_d, end_d = dr[0], dr[1]
        else:
            start_d, end_d = data_min, data_max
    start_d = max(start_d, data_min)
    end_d = min(end_d, data_max)
    start_date, end_date = str(start_d), str(end_d)
    st.caption(f"Applied: {start_date} to {end_date}")
    default_cadence = PRESETS[preset]["cadence"] if preset in PRESETS else "weekly"
    default_role = PRESETS[preset]["role"] if preset in PRESETS else "Owner/GM"
    cadence = st.selectbox("Cadence", ["daily", "weekly", "monthly"], index=["daily", "weekly", "monthly"].index(default_cadence))
    role_options = ["Owner/GM", "Service Manager", "Parts Manager"]
    role = st.selectbox("Role View", role_options, index=role_options.index(default_role))
    compare_prev = st.toggle("Compare to previous period", value=True)
    overhead = st.number_input("Monthly overhead target ($)", min_value=0.0, value=float(cfg["monthly_overhead_target"]), step=10000.0)
    if st.button("Save overhead target", use_container_width=True):
        save_config({"monthly_overhead_target": overhead})
        st.success("Saved.")
    st.markdown("---")
    st.subheader("Ask Your Data")
    st.caption("Ask a KPI question here, or use the Ask Your Data tab.")
    with st.expander("Sample questions (click to use)"):
        for persona, prompts in SAMPLE_QUESTIONS.items():
            st.markdown(f"**{persona}**")
            for idx, prompt in enumerate(prompts):
                if st.button(prompt, key=f"sidebar-sample-{persona}-{idx}", use_container_width=True):
                    st.session_state["sidebar_qa_input"] = prompt
                    st.session_state["qa_prompt"] = prompt
    sidebar_question = st.text_input(
        "Quick question",
        key="sidebar_qa_input",
        placeholder="What is our dead stock ratio?",
    )
    if st.button("Ask now", use_container_width=True):
        if sidebar_question.strip():
            qa_context = QAContext(start_date=start_date, end_date=end_date, overhead_target=float(overhead))
            st.session_state["qa_response"] = answer_question(
                conn,
                sidebar_question.strip(),
                qa_context,
                audit_log_path=str(Path(__file__).resolve().parent / "logs" / "qa_audit.jsonl"),
            )
            st.session_state["qa_prompt"] = sidebar_question.strip()
            st.success("Answer generated. See details in Ask Your Data tab.")
        else:
            st.warning("Enter a question first.")

st.markdown(
    f"<div class='kpi-toolbar'><strong>View</strong>: {role} | <strong>Cadence</strong>: {cadence.title()} | "
    f"<strong>Date Range</strong>: {start_date} to {end_date}</div>",
    unsafe_allow_html=True,
)

owner = owner_metrics(conn, start_date, end_date, overhead)
service = service_metrics(conn, start_date, end_date)
parts = parts_metrics(conn, start_date, end_date)
trend = monthly_trends(conn, start_date, end_date)
quality = run_data_quality_checks(conn)
render_data_status_banner(quality, min_date, max_date, start_date, end_date)

start_dt = parse_iso_date(start_date)
end_dt = parse_iso_date(end_date)
period_days = max((end_dt - start_dt).days + 1, 1)
prev_end_dt = start_dt - timedelta(days=1)
prev_start_dt = prev_end_dt - timedelta(days=period_days - 1)
prev_start_date = prev_start_dt.isoformat()
prev_end_date = prev_end_dt.isoformat()

if compare_prev:
    prev_owner = owner_metrics(conn, prev_start_date, prev_end_date, overhead)
    prev_service = service_metrics(conn, prev_start_date, prev_end_date)
    prev_parts = parts_metrics(conn, prev_start_date, prev_end_date)
else:
    prev_owner = None
    prev_service = None
    prev_parts = None

metric_values = {
    "service_absorption_proxy_pct": owner["service_absorption_proxy_pct"],
    "technician_efficiency_pct": service["technician_efficiency_pct"],
    "open_work_orders_14_plus": float(service["open_work_orders_14_plus"]),
    "parts_turn_r12": parts["parts_turn_r12"],
    "dead_stock_ratio_pct": parts["dead_stock_ratio_pct"],
}
alerts = evaluate_threshold_alerts(metric_values, DEFAULT_THRESHOLDS)
digest = build_digest(cadence, metric_values, alerts)
alerts = alerts.copy()
alerts["status"] = alerts["severity"].str.upper()

overview_tab, role_tab, ask_tab, alert_tab, quality_tab, pilot_tab = st.tabs(
    ["Executive Overview", "Role Dashboard", "Ask Your Data", "Alerts & Digests", "Data Trust", "Pilot Rollout"]
)

with overview_tab:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(
        "Service Absorption % (Proxy)",
        f"{owner['service_absorption_proxy_pct']:.1f}%",
        help=KPI_HELP["service_absorption_proxy_pct"],
        delta=(
            format_delta(owner["service_absorption_proxy_pct"] - prev_owner["service_absorption_proxy_pct"], " pp")
            if compare_prev and prev_owner
            else None
        ),
    )
    c2.metric(
        "Tech Efficiency %",
        f"{service['technician_efficiency_pct']:.1f}%",
        help=KPI_HELP["technician_efficiency_pct"],
        delta=(
            format_delta(service["technician_efficiency_pct"] - prev_service["technician_efficiency_pct"], " pp")
            if compare_prev and prev_service
            else None
        ),
    )
    c3.metric(
        "Open WOs >14 Days",
        f"{service['open_work_orders_14_plus']:,}",
        help=KPI_HELP["open_work_orders_14_plus"],
        delta=(
            format_work_order_delta(service["open_work_orders_14_plus"], prev_service["open_work_orders_14_plus"])
            if compare_prev and prev_service
            else None
        ),
        delta_color="inverse",
    )
    c4.metric(
        "Parts Turn Rate (Proxy)",
        f"{parts['parts_turn_r12']:.2f}",
        help=KPI_HELP["parts_turn_r12"],
        delta=(
            format_delta(parts["parts_turn_r12"] - prev_parts["parts_turn_r12"])
            if compare_prev and prev_parts
            else None
        ),
    )
    c5.metric(
        "Dead Stock Ratio %",
        f"{parts['dead_stock_ratio_pct']:.1f}%",
        help=KPI_HELP["dead_stock_ratio_pct"],
        delta=(
            format_delta(parts["dead_stock_ratio_pct"] - prev_parts["dead_stock_ratio_pct"], " pp")
            if compare_prev and prev_parts
            else None
        ),
        delta_color="inverse",
    )
    if compare_prev:
        st.caption(
            f"Comparison window: previous same-length period ({period_days} days), "
            f"{prev_start_date} to {prev_end_date}. "
            f"'percentage points' = absolute % change (for example, 50% to 55% is +5 percentage points)."
        )
    crit_count = int((alerts["severity"] == "critical").sum())
    warn_count = int((alerts["severity"] == "warning").sum())
    if crit_count or warn_count:
        st.markdown(
            f"Current risk posture: {status_badge(f'{crit_count} critical', 'critical')} | "
            f"{status_badge(f'{warn_count} warning', 'warning')}",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(f"Current risk posture: {status_badge('All core KPIs on target', 'ok')}", unsafe_allow_html=True)
    if not trend.empty:
        fig = px.line(trend, x="month", y="revenue", markers=True, title="Monthly Revenue Trend")
        st.plotly_chart(fig, use_container_width=True)

with role_tab:
    st.subheader(f"{role} View - {cadence.title()} Cadence")
    if role == "Owner/GM":
        st.metric("Total Revenue", f"${owner['total_revenue']:,.0f}", help=KPI_HELP["total_revenue"])
        st.metric(
            "Service Revenue",
            f"${owner['service_revenue']:,.0f}",
            help="Service Revenue is posted labor/service sales in the selected period.",
        )
        st.metric("Parts Gross Profit", f"${owner['parts_gp']:,.0f}", help=KPI_HELP["parts_gp"])
        st.dataframe(alerts[alerts["metric_id"].isin(["service_absorption_proxy_pct", "parts_turn_r12"])], use_container_width=True, hide_index=True)
    elif role == "Service Manager":
        st.metric("Tech Efficiency", f"{service['technician_efficiency_pct']:.1f}%", help=KPI_HELP["technician_efficiency_pct"])
        st.metric(
            "Open Work Orders",
            f"{service['open_work_orders']:,}",
            help="Open Work Orders are service orders not yet finalized/archived/voided.",
        )
        st.metric("Open WO 14+ days", f"{service['open_work_orders_14_plus']:,}", help=KPI_HELP["open_work_orders_14_plus"])
        if not service["weekly_efficiency"].empty:
            fig = px.bar(service["weekly_efficiency"], x="week", y="efficiency_pct", title="Weekly Technician Efficiency")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.metric("Parts Turn Rate", f"{parts['parts_turn_r12']:.2f}", help=KPI_HELP["parts_turn_r12"])
        st.metric(
            "Dead Parts",
            f"{parts['dead_parts']:,}",
            help="Dead Parts are active part numbers with no sales in the trailing 18 months.",
        )
        st.metric(
            "Active Parts",
            f"{parts['active_parts']:,}",
            help="Active Parts are parts currently marked active in the part master.",
        )
        st.metric("Dead Stock Ratio", f"{parts['dead_stock_ratio_pct']:.1f}%", help=KPI_HELP["dead_stock_ratio_pct"])

    with st.expander("KPI Contract (definitions, owners, targets)"):
        st.json(KPI_CONTRACT)
    with st.expander("KPI Glossary (plain language)"):
        st.markdown(
            """
            - **Service Absorption % (Proxy):** How much of your overhead is covered by service + parts gross profit.
            - **Tech Efficiency %:** Billed technician hours divided by available technician hours.
            - **Open WOs >14 Days:** Work orders still open after two weeks; usually a bottleneck signal.
            - **Parts Turn Rate (Proxy):** How quickly parts inventory is moving over time.
            - **Dead Stock Ratio %:** Percent of active parts that have not sold in the trailing 18 months.
            """
        )

with ask_tab:
    st.subheader("Ask Your Data (KPI Q&A)")
    st.caption("Ask KPI-focused questions. Responses are grounded in current filters and approved metric functions.")
    st.markdown("#### Sample questions")
    for persona, prompts in SAMPLE_QUESTIONS.items():
        st.markdown(f"**{persona}**")
        cols = st.columns(3)
        for idx, prompt in enumerate(prompts):
            if cols[idx % 3].button(prompt, key=f"tab-sample-{persona}-{idx}", use_container_width=True):
                st.session_state["qa_prompt"] = prompt
                st.session_state["sidebar_qa_input"] = prompt

    question = st.text_input(
        "Ask a question",
        value=st.session_state.get("qa_prompt", ""),
        placeholder="Example: Why are open work orders over 14 days increasing?",
    )
    if st.button("Get data answer", type="primary", use_container_width=True):
        if question.strip():
            qa_context = QAContext(start_date=start_date, end_date=end_date, overhead_target=float(overhead))
            response = answer_question(
                conn,
                question.strip(),
                qa_context,
                audit_log_path=str(Path(__file__).resolve().parent / "logs" / "qa_audit.jsonl"),
            )
            st.session_state["qa_response"] = response
        else:
            st.warning("Please enter a question first.")
    if st.session_state.get("qa_response"):
        render_qa_response(st.session_state["qa_response"])

with alert_tab:
    st.subheader("Threshold Alerts")
    st.dataframe(alerts[["metric_id", "value", "status", "message"]], use_container_width=True, hide_index=True)
    st.subheader(f"{cadence.title()} Digest")
    st.text(digest)
    st.download_button("Download digest", digest, file_name=f"{cadence}_digest.txt", use_container_width=True)

with quality_tab:
    st.subheader("Data Quality Gates")
    st.dataframe(quality, use_container_width=True, hide_index=True)
    status_counts = quality["status"].value_counts().to_dict() if not quality.empty else {}
    st.caption(f"Pass: {status_counts.get('pass',0)} | Warn: {status_counts.get('warn',0)} | Fail: {status_counts.get('fail',0)}")

with pilot_tab:
    st.subheader("Pilot Rollout Scorecard")
    st.markdown(
        """
        - **Week 1:** baseline capture and KPI formula sign-off
        - **Week 2-3:** manager training and daily/weekly standups
        - **Week 4:** outcome review (absorption, WO aging, dead stock ratio)
        """
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Pilot Stores Target", "5")
    c2.metric("Critical Alerts Open", f"{int((alerts['severity'] == 'critical').sum())}")
    c3.metric("Data Trust Pass Rate", f"{(quality['status'].eq('pass').mean()*100) if not quality.empty else 0:.0f}%")

st.caption("Proxy formulas are labeled where source data lacks explicit fields.")
