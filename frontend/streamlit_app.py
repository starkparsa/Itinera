import os

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="AI Travel Planner", page_icon="🧭", layout="wide")

if "active_conversation_id" not in st.session_state:
    st.session_state.active_conversation_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []  # messages of the currently open chat
if "conversations" not in st.session_state:
    st.session_state.conversations = []  # sidebar chat list


def refresh_conversation_list():
    try:
        res = requests.get(f"{BACKEND_URL}/conversations", timeout=15)
        res.raise_for_status()
        st.session_state.conversations = res.json()
    except requests.exceptions.RequestException:
        pass  # sidebar just won't update this run -- not worth blocking on


def load_conversation(conversation_id: int):
    try:
        res = requests.get(f"{BACKEND_URL}/conversations/{conversation_id}", timeout=15)
        res.raise_for_status()
        data = res.json()
        st.session_state.active_conversation_id = conversation_id
        st.session_state.messages = data["messages"]
    except requests.exceptions.RequestException as exc:
        st.error(f"Couldn't load that chat: {exc}")


def start_new_chat():
    st.session_state.active_conversation_id = None
    st.session_state.messages = []


def render_trip(trip: dict):
    if trip.get("agent_context"):
        st.success(f"🔎 **Agent findings:** {trip['agent_context']}")
    if trip.get("note"):
        st.info(trip["note"])

    days = {}
    for item in trip["itinerary"]:
        days.setdefault(item["day_number"], []).append(item)

    for day_number in sorted(days):
        with st.expander(f"Day {day_number}", expanded=True):
            for item in days[day_number]:
                label = f"**{item['time_of_day']}** — {item['activity']}" if item["time_of_day"] else item["activity"]
                st.markdown(f"- {label}")
                if item.get("notes"):
                    st.caption(item["notes"])


refresh_conversation_list()

# ---------- sidebar: new chat + chat history ----------
with st.sidebar:
    st.markdown("### 🧭 Travel Planner")

    if st.button("+ New chat", use_container_width=True, type="primary"):
        start_new_chat()
        st.rerun()

    trip_length = st.number_input(
        "Trip length (days)", min_value=0, max_value=60, value=0, step=1,
        help="Applies to your next message. Leave at 0 to let the model infer "
             "the length from what you type (e.g. \"a week in Lisbon\").",
    )

    st.caption("Chats")
    for conv in st.session_state.conversations:
        is_active = conv["id"] == st.session_state.active_conversation_id
        label_col, delete_col = st.columns([5, 1])

        with label_col:
            if st.button(
                conv["title"] or "New chat",
                key=f"conv_{conv['id']}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                load_conversation(conv["id"])
                st.rerun()

        with delete_col:
            if st.button("🗑", key=f"del_{conv['id']}", help="Delete this chat"):
                try:
                    requests.delete(f"{BACKEND_URL}/conversations/{conv['id']}", timeout=15)
                except requests.exceptions.RequestException:
                    pass
                if st.session_state.active_conversation_id == conv["id"]:
                    start_new_chat()
                st.rerun()

    if not st.session_state.conversations:
        st.caption("No chats yet — start one below.")

# ---------- main chat area ----------
st.title("🧭 AI Travel Planner")

if not st.session_state.messages:
    st.caption("Describe a trip to start planning. Follow-ups in the same chat (e.g. \"make it a week instead\") reference what you asked before.")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("trip"):
            render_trip(msg["trip"])

prompt = st.chat_input("e.g. 4 days in Lisbon, love food and walking, mid-range budget")

if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)

    got_response = False
    with st.chat_message("assistant"):
        spinner_text = "Thinking — planning a full trip can take a few minutes, quick questions are much faster..."
        with st.spinner(spinner_text):
            try:
                payload = {"prompt": prompt}
                if st.session_state.active_conversation_id:
                    payload["conversation_id"] = st.session_state.active_conversation_id
                if trip_length:
                    payload["days"] = int(trip_length)

                res = requests.post(f"{BACKEND_URL}/trips/generate", json=payload, timeout=900)
                res.raise_for_status()
                data = res.json()
                st.session_state.active_conversation_id = data["conversation_id"]
                got_response = True

                if data.get("reply"):
                    # A question or off-topic turn -- no itinerary was generated.
                    st.markdown(data["reply"])
                elif data.get("trip_id"):
                    # A full itinerary was generated.
                    st.markdown(f"Planned a trip to {data['destination']}.")
                    render_trip(data)
            except requests.exceptions.RequestException as exc:
                st.error(f"Couldn't reach the planner backend: {exc}")

    if got_response:
        # Reload from the backend so the sidebar and message list reflect
        # the canonical, persisted state (including the auto-generated
        # chat title on a brand-new conversation).
        load_conversation(st.session_state.active_conversation_id)
        refresh_conversation_list()
        st.rerun()
