import os
import re
import requests
import pandas as pd
import streamlit as st

API_URL = "https://api.monday.com/v2"

MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_BOARD_ID = os.getenv("MONDAY_BOARD_ID")

st.set_page_config(page_title="PB Commercial Reporting", layout="wide")

st.title("PB Commercial Reporting Test")
st.caption("Filtered pull + board schema debugging")

NEEDED_COLUMNS = [
    "Ops Owner",
    "Client",
    "Media Agency",
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

    status_text.write("Fetching page 1...")

    data = monday_query(
        first_query,
        {
            "board_id": str(MONDAY_BOARD_ID).strip(),
            "column_ids": column_ids,
        },
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

        data = monday_query(
            next_query,
            {
                "cursor": cursor,
                "column_ids": column_ids,
            },
        )

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
    debug_rows = []

    for item in items:
        row = {
            "Item ID": item["id"],
            "Name": item["name"],
        }

        for col in item["column_values"]:
            title = col["column"]["title"]
            text_value = col.get("text")
            raw_value = col.get("value")
            value_type = col.get("type")

            row[title] = text_value
            row[f"{title}__RAW"] = raw_value
            row[f"{title}__TYPE"] = value_type

            debug_rows.append({
                "Item ID": item["id"],
                "Name": item["name"],
                "Column ID": col["id"],
                "Column Title": title,
                "Column Type": value_type,
                "Text Value": text_value,
                "Raw Value": raw_value,
            })

        rows.append(row)

    return pd.DataFrame(rows), pd.DataFrame(debug_rows)


def safe_sum(report, col_name):
    num_col = col_name + " Num"
    if num_col in report.columns:
        return report[num_col].sum()
    return 0.0


if st.button("Pull Filtered PB Reporting Data"):
    with st.spinner("Getting board columns..."):
        board_name, columns = get_board_columns()

    st.subheader(f"Board: {board_name}")

    schema_df = pd.DataFrame(columns)

    st.header("Board Schema")
    st.caption("This tells us what type each monday column is. Formula/mirror/rollup columns may explain blank values.")
    st.dataframe(schema_df, use_container_width=True)

    schema_csv = schema_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Board Schema CSV",
        data=schema_csv,
        file_name="pb_board_schema.csv",
        mime="text/csv",
    )

    found_cols, missing_cols = find_needed_column_ids(columns)

    st.write("Columns found:", len(found_cols))
    st.write("Columns missing:", len(missing_cols))

    with st.expander("Expected column ID mapping"):
        st.json(found_cols)

    if missing_cols:
        st.warning("These expected columns were not found exactly:")
        st.write(missing_cols)

    column_ids = list(found_cols.values())

    with st.spinner("Pulling filtered campaign data..."):
        items = fetch_items_with_columns(column_ids)

    df, debug_df = items_to_dataframe(items)

    st.success(f"Rows pulled: {len(df)}")

    st.subheader("Actual columns returned")
    st.write(df.columns.tolist())

    st.subheader("First 10 rows preview")
    st.dataframe(df.head(10), use_container_width=True)

    st.subheader("Detailed Column Debug")
    st.caption("This shows what monday returned as text/raw/type for each cell.")
    st.dataframe(debug_df.head(500), use_container_width=True)

    numeric_cols = [
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
    ]

    report = df.copy()

    for col in numeric_cols:
        if col in report.columns:
            report[col + " Num"] = report[col].apply(clean_number)

    st.header("Basic Summary")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("MT Leads", f"{safe_sum(report, 'MT: Months Target'):,.0f}")
    c2.metric("MA Leads", f"{safe_sum(report, 'MA: Month Approved'):,.0f}")
    c3.metric("MB Leads", f"{safe_sum(report, 'MB: Monthly Balance'):,.0f}")
    c4.metric("Pending Leads", f"{safe_sum(report, 'Pending'):,.0f}")

    c5, c6, c7 = st.columns(3)
    c5.metric("Monthly Rev Target", f"${safe_sum(report, 'Monthly Rev Target $'):,.0f}")
    c6.metric("Monthly Rev Delivered", f"${safe_sum(report, 'Monthly Rev Delivered $'):,.0f}")
    c7.metric("Monthly Rev Balance", f"${safe_sum(report, 'Monthly Rev Balance $'):,.0f}")

    st.header("Largest Revenue Balances")

    if "Monthly Rev Balance $ Num" in report.columns:
        display_cols = [
            "Name",
            "Ops Owner",
            "Client",
            "Media Agency",
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
        ]

        display_cols = [col for col in display_cols if col in report.columns]

        balance_df = report.sort_values(
            by="Monthly Rev Balance $ Num",
            ascending=False
        )

        st.dataframe(balance_df[display_cols].head(50), use_container_width=True)
    else:
        st.warning("Monthly Rev Balance $ was not found as a readable numeric column.")

    st.header("Download Data")

    csv = report.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Filtered Report CSV",
        data=csv,
        file_name="pb_filtered_reporting_data_debug.csv",
        mime="text/csv",
    )

    debug_csv = debug_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download Debug Column Values CSV",
        data=debug_csv,
        file_name="pb_column_debug_values.csv",
        mime="text/csv",
    )


st.divider()
st.header("May Activity Log Test")

if st.button("Test May Activity Logs"):
    query = """
    query ($board_id: ID!) {
      boards(ids: [$board_id]) {
        activity_logs(limit: 100) {
          id
          event
          data
          created_at
          user_id
        }
      }
    }
    """

    data = monday_query(query, {"board_id": str(MONDAY_BOARD_ID).strip()})
    st.json(data)
