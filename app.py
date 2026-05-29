import os
import re
import json
import requests
import pandas as pd
import streamlit as st
from datetime import date

API_URL = "https://api.monday.com/v2"

MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_BOARD_ID = os.getenv("MONDAY_BOARD_ID")

st.set_page_config(page_title="PB Commercial Weekly Reporting", layout="wide")

st.title("PB Commercial Weekly Reporting")
st.caption("PB - Live 🟣 | Current board data + weekly activity movement")

NEEDED_COLUMNS = [
    "Ops Owner",
    "Client",
    "Media Agency",
    "Go Live Date",
    "MT: Months Target",
    "Pending",
    "MA: Month Approved",
    "MB: Monthly Balance",
    "OT: Order Total",
    "TA: Total Approved",
    "OB: Order Balance",
    "CPL ($)",
    "Monthly Rev Target $",
    "Monthly Rev Delivered $",
    "Monthly Rev Balance $",
    "Pacing",
    "Status",
    "Stage",
    "T:May-26",
    "T:Jun-26",
    "SF_Delivered",
]

TRACKED_ACTIVITY_COLUMNS = [
    "MA: Month Approved",
    "Pending",
    "SF_Delivered",
    "OT: Order Total",
    "T:May-26",
    "T:Jun-26",
    "Go Live Date",
    "Status",
    "Stage",
]

NUMERIC_ACTIVITY_COLUMNS = [
    "MA: Month Approved",
    "Pending",
    "SF_Delivered",
    "OT: Order Total",
    "T:May-26",
    "T:Jun-26",
]


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

    response = requests.post(
        API_URL,
        json={"query": query, "variables": variables or {}},
        headers=headers,
    )

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
    text = (
        text.replace(",", "")
        .replace("$", "")
        .replace("€", "")
        .replace("£", "")
        .replace("%", "")
        .strip()
    )

    match = re.search(r"-?\d+(\.\d+)?", text)
    if not match:
        return 0.0

    return float(match.group())


def extract_value(obj):
    if obj is None:
        return None

    if isinstance(obj, dict):
        if "value" in obj and isinstance(obj["value"], (int, float, str)):
            return obj["value"]

        if "date" in obj:
            return obj["date"]

        if "label" in obj and isinstance(obj["label"], dict):
            return obj["label"].get("text")

        if "text" in obj:
            return obj.get("text")

    if isinstance(obj, (int, float, str)):
        return obj

    return None


def safe_change(old_value, new_value):
    try:
        old_num = 0 if old_value is None or old_value == "" else float(old_value)
        new_num = 0 if new_value is None or new_value == "" else float(new_value)
        return new_num - old_num
    except Exception:
        return None


def get_best_activity_datetime(activity):
    raw_data = activity.get("data")

    try:
        parsed = json.loads(raw_data)
        for key in ["value", "previous_value"]:
            val = parsed.get(key)
            if isinstance(val, dict) and val.get("changed_at"):
                return pd.to_datetime(val.get("changed_at"), utc=True, errors="coerce")
    except Exception:
        pass

    try:
        created = str(activity.get("created_at"))
        if len(created) > 13:
            created = created[:13]
        return pd.to_datetime(int(created), unit="ms", utc=True)
    except Exception:
        return pd.NaT


def week_label(dt):
    if pd.isna(dt):
        return "Unknown"

    dt = pd.to_datetime(dt)
    month_end = dt.replace(day=1) + pd.offsets.MonthEnd(0)

    week_num = ((dt.day - 1) // 7) + 1
    start_day = ((week_num - 1) * 7) + 1
    end_day = min(start_day + 6, month_end.day)

    start_date = dt.replace(day=start_day)
    end_date = dt.replace(day=end_day)

    return f"Week {week_num}: {start_date.strftime('%d %b')} - {end_date.strftime('%d %b')}"


def get_board_columns():
    query = """
    query ($board_id: ID!) {
      boards(ids: [$board_id]) {
        id
        name
        columns {
          id
          title
          type
          settings_str
        }
      }
    }
    """

    data = monday_query(query, {"board_id": str(MONDAY_BOARD_ID).strip()})
    board = data["data"]["boards"][0]
    return board["name"], board["columns"]


def find_needed_column_ids(columns):
    found = {}
    missing = []
    title_to_col = {col["title"].strip(): col for col in columns}

    for needed in NEEDED_COLUMNS:
        if needed in title_to_col:
            found[needed] = title_to_col[needed]["id"]
        else:
            missing.append(needed)

    return found, missing


def fetch_items_with_columns(column_ids):
    all_items = []
    cursor = None
    page_count = 0

    progress_bar = st.progress(0)
    status_text = st.empty()

    first_query = """
    query ($board_id: ID!, $column_ids: [String!]) {
      boards(ids: [$board_id]) {
        items_page(limit: 100) {
          cursor
          items {
            id
            name
            column_values(ids: $column_ids) {
              id
              text
              value
              type
              column {
                title
              }
            }
          }
        }
      }
    }
    """

    status_text.write("Fetching current board page 1...")

    data = monday_query(
        first_query,
        {"board_id": str(MONDAY_BOARD_ID).strip(), "column_ids": column_ids},
    )

    page = data["data"]["boards"][0]["items_page"]
    all_items.extend(page["items"])
    cursor = page.get("cursor")
    page_count += 1

    progress_bar.progress(10)
    status_text.write(f"Fetched page {page_count}. Rows so far: {len(all_items)}")

    while cursor:
        next_query = """
        query ($cursor: String!, $column_ids: [String!]) {
          next_items_page(cursor: $cursor, limit: 100) {
            cursor
            items {
              id
              name
              column_values(ids: $column_ids) {
                id
                text
                value
                type
                column {
                  title
                }
              }
            }
          }
        }
        """

        status_text.write(
            f"Fetching page {page_count + 1}... Rows so far: {len(all_items)}"
        )

        data = monday_query(next_query, {"cursor": cursor, "column_ids": column_ids})

        page = data["data"]["next_items_page"]
        all_items.extend(page["items"])
        cursor = page.get("cursor")
        page_count += 1

        progress_bar.progress(min(95, 10 + page_count * 10))
        status_text.write(f"Fetched page {page_count}. Rows so far: {len(all_items)}")

    progress_bar.progress(100)
    status_text.write(f"Done. Pulled {len(all_items)} rows across {page_count} pages.")

    return all_items


def items_to_dataframe(items):
    rows = []

    for item in items:
        row = {
            "Item ID": item["id"],
            "Name": item["name"],
        }

        for col in item["column_values"]:
            title = col["column"]["title"]
            row[title] = col.get("text")
            row[f"{title}__RAW"] = col.get("value")
            row[f"{title}__TYPE"] = col.get("type")

        rows.append(row)

    return pd.DataFrame(rows)


def fetch_activity_logs(limit=5000):
    query = """
    query ($board_id: ID!, $limit: Int!) {
      boards(ids: [$board_id]) {
        activity_logs(limit: $limit) {
          id
          event
          data
          created_at
          user_id
        }
      }
    }
    """

    data = monday_query(
        query,
        {"board_id": str(MONDAY_BOARD_ID).strip(), "limit": limit},
    )

    return data["data"]["boards"][0]["activity_logs"]


def parse_activity_logs(activity_logs):
    rows = []

    for activity in activity_logs:
        raw_data = activity.get("data")

        try:
            parsed = json.loads(raw_data)
        except Exception:
            continue

        event = activity.get("event")
        column_title = parsed.get("column_title")

        pulse_id = parsed.get("pulse_id") or parsed.get("item_id")
        pulse_name = parsed.get("pulse_name") or parsed.get("item_name")

        new_value = extract_value(parsed.get("value"))
        old_value = extract_value(parsed.get("previous_value"))
        change = safe_change(old_value, new_value)

        activity_dt = get_best_activity_datetime(activity)

        rows.append(
            {
                "Activity ID": activity.get("id"),
                "Event": event,
                "Activity Date": activity_dt,
                "Week": week_label(activity_dt),
                "Item ID": pulse_id,
                "Campaign": pulse_name,
                "Column ID": parsed.get("column_id"),
                "Column Title": column_title,
                "Old Value": old_value,
                "New Value": new_value,
                "Change": change,
                "User ID": activity.get("user_id"),
                "Raw Data": raw_data,
            }
        )

    df = pd.DataFrame(rows)

    if not df.empty:
        df["Activity Date"] = pd.to_datetime(
            df["Activity Date"], errors="coerce", utc=True
        )
        df = df.sort_values("Activity Date", ascending=False)

    return df


def numeric_current_summary(df):
    summary_cols = [
        "Pending",
        "MA: Month Approved",
        "OT: Order Total",
        "T:May-26",
        "T:Jun-26",
        "SF_Delivered",
    ]

    summary = {}

    for col in summary_cols:
        if col in df.columns:
            nums = df[col].apply(clean_number)
            summary[col] = nums.sum()
        else:
            summary[col] = 0

    return summary


def download_button(df, label, filename):
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(label, data=csv, file_name=filename, mime="text/csv")


# -------------------------
# Sidebar controls
# -------------------------

st.sidebar.header("Controls")

activity_limit = st.sidebar.number_input(
    "Activity log records to pull",
    min_value=1000,
    max_value=10000,
    value=5000,
    step=1000,
)

start_date = st.sidebar.date_input("Start date", value=date(2026, 5, 1))
end_date = st.sidebar.date_input("End date", value=date(2026, 5, 31))


# -------------------------
# Current board pull
# -------------------------

st.header("1. Current PB Board Position")

if st.button("Pull Current Board Data"):
    board_name, columns = get_board_columns()
    st.subheader(f"Board: {board_name}")

    found_cols, missing_cols = find_needed_column_ids(columns)

    st.write("Columns found:", len(found_cols))
    st.write("Columns missing:", len(missing_cols))

    if missing_cols:
        st.warning("Missing expected columns:")
        st.write(missing_cols)

    with st.expander("Column mapping"):
        st.json(found_cols)

    items = fetch_items_with_columns(list(found_cols.values()))
    current_df = items_to_dataframe(items)

    st.success(f"Rows pulled: {len(current_df)}")

    current_summary = numeric_current_summary(current_df)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Current MA Approved", f"{current_summary['MA: Month Approved']:,.0f}")
    c2.metric("Current Pending", f"{current_summary['Pending']:,.0f}")
    c3.metric("Order Total", f"{current_summary['OT: Order Total']:,.0f}")
    c4.metric("SF Delivered", f"{current_summary['SF_Delivered']:,.0f}")

    c5, c6 = st.columns(2)
    c5.metric("T:May-26", f"{current_summary['T:May-26']:,.0f}")
    c6.metric("T:Jun-26", f"{current_summary['T:Jun-26']:,.0f}")

    st.subheader("Current Data Preview")
    st.dataframe(current_df.head(200), use_container_width=True)

    download_button(
        current_df,
        "Download Current Board Data CSV",
        "pb_current_board_data.csv",
    )


# -------------------------
# Activity reporting
# -------------------------

st.header("2. Weekly Activity Reporting")

if st.button("Pull Weekly Activity"):
    with st.spinner("Pulling monday activity logs..."):
        logs = fetch_activity_logs(limit=int(activity_limit))

    activity_df = parse_activity_logs(logs)

    if activity_df.empty:
        st.warning("No activity logs returned.")
        st.stop()

    start_ts = pd.Timestamp(start_date, tz="UTC")
    end_ts = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)

    activity_df = activity_df[
        (activity_df["Activity Date"] >= start_ts)
        & (activity_df["Activity Date"] < end_ts)
    ].copy()

    st.success(f"Parsed activity rows in selected date range: {len(activity_df)}")

    tracked_df = activity_df[
        activity_df["Column Title"].isin(TRACKED_ACTIVITY_COLUMNS)
    ].copy()

    numeric_df = tracked_df[
        tracked_df["Column Title"].isin(NUMERIC_ACTIVITY_COLUMNS)
        & tracked_df["Change"].notna()
    ].copy()

    st.subheader("Executive Weekly Movement")

    if numeric_df.empty:
        st.warning("No numeric activity found for tracked reporting columns.")
    else:
        weekly_summary = (
            numeric_df.groupby(["Week", "Column Title"], dropna=False)
            .agg(
                Total_Change=("Change", "sum"),
                Event_Count=("Activity ID", "count"),
            )
            .reset_index()
        )

        weekly_pivot = weekly_summary.pivot_table(
            index="Week",
            columns="Column Title",
            values="Total_Change",
            aggfunc="sum",
            fill_value=0,
        ).reset_index()

        st.dataframe(weekly_pivot, use_container_width=True)

        st.subheader("Weekly Activity Detail")
        st.dataframe(
            numeric_df[
                [
                    "Activity Date",
                    "Week",
                    "Campaign",
                    "Column Title",
                    "Old Value",
                    "New Value",
                    "Change",
                    "Event",
                    "User ID",
                ]
            ],
            use_container_width=True,
        )

        st.subheader("Top Campaign Movements")

        top_campaigns = (
            numeric_df.groupby(["Campaign", "Column Title"], dropna=False)
            .agg(
                Total_Change=("Change", "sum"),
                Event_Count=("Activity ID", "count"),
            )
            .reset_index()
            .sort_values("Total_Change", ascending=False)
        )

        st.dataframe(top_campaigns.head(100), use_container_width=True)

        download_button(
            weekly_pivot,
            "Download Weekly Pivot CSV",
            "pb_weekly_activity_pivot.csv",
        )

        download_button(
            numeric_df,
            "Download Numeric Activity Detail CSV",
            "pb_numeric_activity_detail.csv",
        )

    st.subheader("All Parsed Activity")
    st.dataframe(activity_df, use_container_width=True)

    download_button(
        activity_df,
        "Download All Parsed Activity CSV",
        "pb_all_parsed_activity.csv",
    )
