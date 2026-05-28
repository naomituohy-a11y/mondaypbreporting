import os
import requests
import pandas as pd
import streamlit as st

API_URL = "https://api.monday.com/v2"

MONDAY_API_TOKEN = os.getenv("MONDAY_API_TOKEN")
MONDAY_BOARD_ID = os.getenv("MONDAY_BOARD_ID")

def monday_query(query, variables=None):
    headers = {
        "Authorization": MONDAY_API_TOKEN,
        "Content-Type": "application/json",
    }

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    response = requests.post(API_URL, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()

st.title("PB Commercial Reporting Test")

st.write("This test connects only to the PB / Prospect Base board.")

if st.button("Test monday connection"):
    query = """
    query ($board_id: [ID!]) {
      boards(ids: $board_id) {
        id
        name
      }
    }
    """

    data = monday_query(query, {"board_id": [MONDAY_BOARD_ID]})
    st.json(data)
