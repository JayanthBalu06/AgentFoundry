"""Human-approval dashboard: review and decide on pending escalations.

Run with: streamlit run streamlit_app/approval_dashboard.py
"""
from __future__ import annotations

import os

import httpx
import streamlit as st

BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="AgentFoundry — Approvals", layout="wide")
st.title("AgentFoundry — Human Approval Queue")

client = httpx.Client(base_url=BASE_URL, timeout=10.0)

with st.sidebar:
    st.header("Look up a task")
    user_id = st.text_input("User ID", value="demo-user")
    if st.button("List tasks") and user_id:
        tasks = client.get("/tasks", params={"user_id": user_id}).json()
        for t in tasks:
            st.write(f"**{t['id']}** — {t['status']} — {t['goal'][:60]}")

st.subheader("Pending approvals")

try:
    pending = client.get("/approvals").json()
except httpx.ConnectError:
    st.error(f"Could not reach the API at {BASE_URL}. Is it running?")
    st.stop()

if not pending:
    st.info("Nothing waiting on a human right now.")

for approval in pending:
    with st.container(border=True):
        st.markdown(f"**{approval['level'].upper()}** · task `{approval['task_id']}` · reason: `{approval['reason']}`")
        st.write(approval["summary"])
        with st.expander("Payload"):
            st.json(approval["payload"])

        note = st.text_input("Reviewer note", key=f"note-{approval['id']}")
        col1, col2 = st.columns(2)
        if col1.button("Approve", key=f"approve-{approval['id']}"):
            client.post(f"/approvals/{approval['id']}/decide", json={"approved": True, "note": note})
            st.rerun()
        if col2.button("Reject", key=f"reject-{approval['id']}"):
            client.post(f"/approvals/{approval['id']}/decide", json={"approved": False, "note": note})
            st.rerun()
