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

if st.button("Pull PB Campaign Rows"):
    query = """
    query ($board_id: ID!) {
      boards(ids: [$board_id]) {
        id
        name
        items_page(limit: 25) {
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

    data = monday_query(query, {"board_id": str(MONDAY_BOARD_ID).strip()})

    board = data["data"]["boards"][0]
    items = board["items_page"]["items"]

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

    st.subheader(f"Board: {board['name']}")
    st.write(f"Rows pulled: {len(df)}")
    st.dataframe(df)
