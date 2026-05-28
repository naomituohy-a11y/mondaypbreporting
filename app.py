import os
import requests
import pandas as pd
import streamlit as st

API_URL = "https://api.monday.com/v2"

MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_BOARD_ID = os.getenv("MONDAY_BOARD_ID")

st.title("PB Commercial Reporting Test")
st.write("Connected board ID:", MONDAY_BOARD_ID)

def monday_query(query, variables=None):
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

    return board_name, all_items

if st.button("Pull ALL PB Campaign Rows"):
    board_name, items = fetch_all_items()

    rows = []

    for item in items:
        row = {
            "Item ID": item["id"],
            "Name": item["name"],
        }

        for col in item["column_values"]:
            col_title = col["column"]["title"]
            row[col_title] = col.get("text")

        rows.append(row)

    df = pd.DataFrame(rows)

    st.subheader(f"Board: {board_name}")
    st.write(f"Rows pulled: {len(df)}")
    st.dataframe(df)

    csv = df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download CSV",
        data=csv,
        file_name="pb_commercial_campaigns.csv",
        mime="text/csv",
    )
