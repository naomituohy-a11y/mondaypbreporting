import os
import re
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import date, datetime

API_URL = "https://api.monday.com/v2"

MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_BOARD_ID = os.getenv("MONDAY_BOARD_ID")

st.set_page_config(page_title="PB Commercial Reporting", layout="wide")

st.title("PB Commercial Reporting Dashboard")
st.caption("Connected to monday.com board: PB - Live 🟣")

# -----------------------------
# Helpers
# -----------------------------

def monday_query(query, variables=None):
    if not MONDAY_API_TOKEN:
        st.error("MONDAY_API_TOKEN is missing in Railway variables.")
        st.stop()

    if not MONDAY_BOARD_ID:
        st.error("MONDAY_BOARD_ID is missing in Railway variables.")
        st.stop()

    headers = {
        "Authorization": MONDAY_API_TOKEN.strip(),
        "Content-Type": "application/json",
    }

    payload = {"query": query, "variables": variables or {}}
    response = requests.post(API_URL, json=payload, headers=headers)

    if response.status_code != 200:
        st.error(f"HTTP Error: {response.status_code}")
        st.code(response.text)
        response.raise_for_status()

    data = response.json()

    if "errors" in data:
        st.error("Monday API returned errors:")
        st.json(data["errors"])

    return data


def clean_number(value):
    if value is None or value == "":
        return 0.0

    text = str(value)
    text = text.replace(",", "")
    text = text.replace("$", "")
    text = text.replace("€", "")
    text = text.replace("£", "")
    text = text.replace("%", "")
    text = text.strip()

    match = re.search(r"-?\d+(\.\d+)?", text)
    if not match:
        return 0.0

    return float(match.group())


def parse_date(value):
    if value is None or value == "":
        return pd.NaT

    return pd.to_datetime(value, errors="coerce", dayfirst=False)


def week_of_month(dt):
    if pd.isna(dt):
        return None

    first_day = dt.replace(day=1)
    adjusted_day = dt.day + first_day.weekday()
    return int((adjusted_day - 1) / 7) + 1


def week_range_label(dt):
    if pd.isna(dt):
        return None

    month_start = dt.replace(day=1)
    month_end = month_start + pd.offsets.MonthEnd(0)

    week_num = week_of_month(dt)

    start_day = 1
    current_week = 1

    while current_week < week_num:
        candidate = month_start + pd.Timedelta(days=(7 - month_start.weekday()) if current_week == 1 else 7)
        start_day = candidate.day
        month_start = candidate
        current_week += 1

    week_start = month_start
    week_end = min(week_start + pd.Timedelta(days=6), month_end)

    return f"Week {week_num}: {week_start.strftime('%d %b')} - {week_end.strftime('%d %b')}"


def get_col(df, possible_names):
    for name in possible_names:
        if name in df.columns:
            return name
    return None


# -----------------------------
# Monday fetch
# -----------------------------

@st.cache_data(ttl=300)
def fetch_all_items():
    all_items = []
    cursor = None
    board_name = None

    first_query = """
    query ($board_id: ID!) {
      boards(ids: [$board_id]) {
        id
        name
        items_page(limit: 100) {
          cursor
          items {
            id
            name
            column_values {
              id
              text
              value
              column {
                title
              }
            }
          }
        }
      }
    }
    """

    data = monday_query(first_query, {"board_id": str(MONDAY_BOARD_ID).strip()})
    board = data["data"]["boards"][0]
    board_name = board["name"]

    page = board["items_page"]
    all_items.extend(page["items"])
    cursor = page.get("cursor")

    while cursor:
        next_query = """
        query ($cursor: String!) {
          next_items_page(cursor: $cursor, limit: 100) {
            cursor
            items {
              id
              name
              column_values {
                id
                text
                value
                column {
                  title
                }
              }
            }
          }
        }
        """

        data = monday_query(next_query, {"cursor": cursor})
        page = data["data"]["next_items_page"]
        all_items.extend(page["items"])
        cursor = page.get("cursor")

    rows = []

    for item in all_items:
        row = {
            "Item ID": item["id"],
            "Name": item["name"],
        }

        for col in item["column_values"]:
            title = col["column"]["title"]
            row[title] = col.get("text")

        rows.append(row)

    df = pd.DataFrame(rows)

    return board_name, df


# -----------------------------
# App
# -----------------------------

if st.button("Refresh PB Board Data"):
    st.cache_data.clear()

board_name, df = fetch_all_items()

st.subheader(f"Board: {board_name}")
st.write(f"Rows pulled: {len(df)}")

# Identify expected columns
client_col = get_col(df, ["Client"])
campaign_col = get_col(df, ["Campaign Name (Closed ref)", "Campaign Name"])
go_live_col = get_col(df, ["Go Live Date"])
status_col = get_col(df, ["Status"])
stage_col = get_col(df, ["Stage"])

mt_leads_col = get_col(df, ["MT: Months Target", "MT: Month Target"])
ma_leads_col = get_col(df, ["MA: Month Approved"])
mb_leads_col = get_col(df, ["MB: Monthly Balance"])
pending_leads_col = get_col(df, ["Pending"])
delivered_col = get_col(df, ["Delivered"])

mt_rev_col = get_col(df, ["Monthly Rev Target $"])
ma_rev_col = get_col(df, ["Monthly Rev Delivered $", "Month Rev Dev"])
mb_rev_col = get_col(df, ["Monthly Rev Balance $"])
pending_rev_col = get_col(df, ["Revenue Pending", "Pending $"])

required_check = {
    "Client": client_col,
    "Campaign Name": campaign_col,
    "Go Live Date": go_live_col,
    "MT Leads": mt_leads_col,
    "MA Leads": ma_leads_col,
    "MB Leads": mb_leads_col,
    "Pending Leads": pending_leads_col,
    "Delivered": delivered_col,
    "MT Revenue": mt_rev_col,
    "MA Revenue": ma_rev_col,
    "MB Revenue": mb_rev_col,
    "Pending Revenue": pending_rev_col,
    "Status": status_col,
    "Stage": stage_col,
}

with st.expander("Column mapping check"):
    st.json(required_check)

# Clean dashboard dataframe
report = df.copy()

for col in [mt_leads_col, ma_leads_col, mb_leads_col, pending_leads_col, delivered_col,
            mt_rev_col, ma_rev_col, mb_rev_col, pending_rev_col]:
    if col:
        report[col + " (num)"] = report[col].apply(clean_number)

if go_live_col:
    report["Go Live Parsed"] = report[go_live_col].apply(parse_date)
else:
    report["Go Live Parsed"] = pd.NaT

today = pd.Timestamp(date.today())
current_month = today.month
current_year = today.year

report["Is Live"] = report["Go Live Parsed"].notna() & (report["Go Live Parsed"] <= today)
report["Is Current Month Go Live"] = (
    report["Go Live Parsed"].notna()
    & (report["Go Live Parsed"].dt.month == current_month)
    & (report["Go Live Parsed"].dt.year == current_year)
)

report["Go Live Week"] = report["Go Live Parsed"].apply(week_range_label)

# Metric values
def total_num(col):
    if col and col + " (num)" in report.columns:
        return report[col + " (num)"].sum()
    return 0.0

total_mt_leads = total_num(mt_leads_col)
total_ma_leads = total_num(ma_leads_col)
total_mb_leads = total_num(mb_leads_col)
total_pending_leads = total_num(pending_leads_col)

total_mt_rev = total_num(mt_rev_col)
total_ma_rev = total_num(ma_rev_col)
total_mb_rev = total_num(mb_rev_col)
total_pending_rev = total_num(pending_rev_col)

live_rev = report.loc[report["Is Live"], mt_rev_col + " (num)"].sum() if mt_rev_col else 0
not_live_rev = report.loc[~report["Is Live"], mt_rev_col + " (num)"].sum() if mt_rev_col else 0

live_leads = report.loc[report["Is Live"], mt_leads_col + " (num)"].sum() if mt_leads_col else 0
not_live_leads = report.loc[~report["Is Live"], mt_leads_col + " (num)"].sum() if mt_leads_col else 0

# -----------------------------
# Dashboard
# -----------------------------

st.header("Executive Summary")

c1, c2, c3, c4 = st.columns(4)

c1.metric("MT Revenue", f"${total_mt_rev:,.0f}")
c2.metric("MA Revenue", f"${total_ma_rev:,.0f}")
c3.metric("MB Revenue", f"${total_mb_rev:,.0f}")
c4.metric("Pending Revenue", f"${total_pending_rev:,.0f}")

c5, c6, c7, c8 = st.columns(4)

c5.metric("MT Leads", f"{total_mt_leads:,.0f}")
c6.metric("MA Leads", f"{total_ma_leads:,.0f}")
c7.metric("MB Leads", f"{total_mb_leads:,.0f}")
c8.metric("Pending Leads", f"{total_pending_leads:,.0f}")

st.header("Live vs Not Yet Live")

c9, c10, c11, c12 = st.columns(4)

c9.metric("Live Revenue", f"${live_rev:,.0f}")
c10.metric("Not Yet Live Revenue", f"${not_live_rev:,.0f}")
c11.metric("Live Leads", f"{live_leads:,.0f}")
c12.metric("Not Yet Live Leads", f"{not_live_leads:,.0f}")

st.header("Weekly Go-Live / Revenue Drop-In View")

weekly = report[report["Is Current Month Go Live"]].copy()

if not weekly.empty:
    weekly_summary = weekly.groupby("Go Live Week", dropna=False).agg(
        Revenue_Became_Live=(mt_rev_col + " (num)", "sum") if mt_rev_col else ("Item ID", "count"),
        Leads_Became_Live=(mt_leads_col + " (num)", "sum") if mt_leads_col else ("Item ID", "count"),
        Campaigns=("Item ID", "count"),
    ).reset_index()

    st.dataframe(weekly_summary, use_container_width=True)

    fig = px.bar(
        weekly_summary,
        x="Go Live Week",
        y="Revenue_Became_Live",
        title="Revenue Became Live by Week"
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No current-month go-live campaigns found.")

st.header("Biggest Revenue Balances")

if mb_rev_col:
    balance_cols = ["Name"]
    for optional_col in [client_col, campaign_col, go_live_col, status_col, stage_col]:
        if optional_col:
            balance_cols.append(optional_col)

    balance_cols += [
        mt_rev_col + " (num)",
        ma_rev_col + " (num)" if ma_rev_col else None,
        mb_rev_col + " (num)",
        mt_leads_col + " (num)" if mt_leads_col else None,
        ma_leads_col + " (num)" if ma_leads_col else None,
        mb_leads_col + " (num)" if mb_leads_col else None,
    ]

    balance_cols = [c for c in balance_cols if c and c in report.columns]

    balance_df = report[balance_cols].copy()
    balance_df = balance_df.sort_values(by=mb_rev_col + " (num)", ascending=False)

    st.dataframe(balance_df.head(30), use_container_width=True)
else:
    st.warning("Could not find Monthly Rev Balance column.")

st.header("Raw PB Board Data")

st.dataframe(report, use_container_width=True)

csv = report.to_csv(index=False).encode("utf-8")
st.download_button(
    label="Download Full Report CSV",
    data=csv,
    file_name="pb_commercial_reporting_output.csv",
    mime="text/csv",
)
