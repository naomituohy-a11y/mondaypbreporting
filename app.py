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
st.caption("Filtered pull: only reporting columns, not the entire Monday universe. Sensible. Disturbing.")

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
              column {
                title
              }
            }
          }
        }
      }
    }
    """

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
                column {
                  title
                }
              }
            }
          }
        }
        """

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

        rows.append(row)

    return pd.DataFrame(rows)


if st.button("Pull Filtered PB Reporting Data"):
    with st.spinner("Getting board columns..."):
        board_name, columns = get_board_columns()

    st.subheader(f"Board: {board_name}")

    found_cols, missing_cols = find_needed_column_ids(columns)

    st.write("Columns found:", len(found_cols))
    st.write("Columns missing:", len(missing_cols))

    with st.expander("Column ID mapping"):
        st.json(found_cols)

    if missing_cols:
        st.warning("These expected columns were not found:")
        st.write(missing_cols)

    column_ids = list(found_cols.values())

    with st.spinner("Pulling filtered campaign data..."):
        items = fetch_items_with_columns(column_ids)

    df = items_to_dataframe(items)

    st.success(f"Rows pulled: {len(df)}")
    st.dataframe(df, use_container_width=True)

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
    c1.metric("MT Leads", f"{report.get('MT: Months Target Num', pd.Series([0])).sum():,.0f}")
    c2.metric("MA Leads", f"{report.get('MA: Month Approved Num', pd.Series([0])).sum():,.0f}")
    c3.metric("MB Leads", f"{report.get('MB: Monthly Balance Num', pd.Series([0])).sum():,.0f}")
    c4.metric("Pending Leads", f"{report.get('Pending Num', pd.Series([0])).sum():,.0f}")

    c5, c6, c7 = st.columns(3)
    c5.metric("Monthly Rev Target", f"${report.get('Monthly Rev Target $ Num', pd.Series([0])).sum():,.0f}")
    c6.metric("Monthly Rev Delivered", f"${report.get('Monthly Rev Delivered $ Num', pd.Series([0])).sum():,.0f}")
    c7.metric("Monthly Rev Balance", f"${report.get('Monthly Rev Balance $ Num', pd.Series([0])).sum():,.0f}")

    st.header("Largest Revenue Balances")

    if "Monthly Rev Balance $ Num" in report.columns:
        sort_cols = [
            "Name",
            "Ops Owner",
            "Client",
            "Media Agency",
            "MT: Months Target",
            "MA: Month Approved",
            "MB: Monthly Balance",
            "Monthly Rev Target $",
            "Monthly Rev Delivered $",
            "Monthly Rev Balance $",
            "Pacing",
        ]

        sort_cols = [col for col in sort_cols if col in report.columns]

        balance_df = report.sort_values(
            by="Monthly Rev Balance $ Num",
            ascending=False
        )

        st.dataframe(balance_df[sort_cols].head(30), use_container_width=True)

    csv = report.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download Filtered Report CSV",
        data=csv,
        file_name="pb_filtered_reporting_data.csv",
        mime="text/csv",
    )
