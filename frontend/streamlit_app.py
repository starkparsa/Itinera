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


def _weather_icon(condition: str) -> str:
    """Small keyword lookup, not an LLM call -- see backend/app/weather_service.py."""
    c = condition.lower()
    if "thunder" in c:
        return "⛈️"
    if "snow" in c:
        return "❄️"
    if "rain" in c or "drizzle" in c:
        return "🌧️"
    if "fog" in c:
        return "🌫️"
    if "overcast" in c or "cloud" in c:
        return "☁️"
    if "clear" in c:
        return "☀️"
    return "🌤️"


def _get_ics_bytes(trip_id: int) -> bytes | None:
    """Fetches a trip's .ics export once and caches it in session_state --
    Streamlit reruns the whole script on every interaction (typing, sidebar
    clicks), and this avoids refetching on every unrelated rerun."""
    cache = st.session_state.setdefault("ics_cache", {})
    if trip_id not in cache:
        try:
            res = requests.get(f"{BACKEND_URL}/trips/{trip_id}/calendar.ics", timeout=15)
            res.raise_for_status()
            cache[trip_id] = res.content
        except requests.exceptions.RequestException:
            return None
    return cache[trip_id]


def _latest_exportable_trip() -> dict | None:
    """Newest trip in the active conversation with a resolved start_date --
    export only becomes available once one exists (see CLAUDE.md decision
    log), so this returns None (button stays hidden entirely) otherwise."""
    for msg in reversed(st.session_state.messages):
        trip = msg.get("trip")
        if trip and trip.get("start_date") and trip.get("trip_id"):
            return trip
    return None


def render_trip(trip: dict):
    if trip.get("agent_context"):
        st.success(f"🔎 **Agent findings:** {trip['agent_context']}")
    if trip.get("note"):
        st.info(trip["note"])

    days = {}
    for item in trip["itinerary"]:
        days.setdefault(item["day_number"], []).append(item)

    # Real-time per-day forecast, only present for days within Open-Meteo's
    # horizon with a resolvable trip start date -- see date_resolver.py /
    # weather_service.py. Absent entirely for a day is normal, not an error.
    weather_by_day = {w["day_number"]: w for w in trip.get("weather", [])}

    for day_number in sorted(days):
        with st.expander(f"Day {day_number}", expanded=True):
            weather = weather_by_day.get(day_number)
            if weather:
                icon = _weather_icon(weather["condition"])
                st.caption(
                    f"{icon} High {weather['temp_max']:.0f}°C / {weather['temp_max_f']:.0f}°F "
                    f"— Low {weather['temp_min']:.0f}°C / {weather['temp_min_f']:.0f}°F — {weather['condition']}"
                )
            for item in days[day_number]:
                label = f"**{item['time_of_day']}** — {item['activity']}" if item["time_of_day"] else item["activity"]
                st.markdown(f"- {label}")
                if item.get("notes"):
                    st.caption(item["notes"])

    # Export is only offered once a real start date was resolved -- hidden
    # entirely otherwise, never a disabled button or a guessed date (see
    # CLAUDE.md decision log).
    if trip.get("start_date") and trip.get("trip_id"):
        st.markdown("---")
        ics_bytes = _get_ics_bytes(trip["trip_id"])
        if ics_bytes:
            st.download_button(
                "📅 Add this itinerary to your calendar",
                data=ics_bytes,
                file_name=f"trip-{trip['trip_id']}.ics",
                mime="text/calendar",
                key=f"ics_download_inline_{trip['trip_id']}",
            )


refresh_conversation_list()

# ---------- sidebar: new chat + chat history ----------
with st.sidebar:
    st.markdown("### 🧭 Travel Planner")

    if st.button("+ New chat", use_container_width=True, type="primary"):
        start_new_chat()
        st.rerun()

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
title_col, export_col = st.columns([4, 1])
with title_col:
    st.title("🧭 AI Travel Planner")

_latest_trip = _latest_exportable_trip()
if _latest_trip:
    with export_col:
        st.write("")  # nudge the button down to roughly align with the title
        ics_bytes = _get_ics_bytes(_latest_trip["trip_id"])
        if ics_bytes:
            st.download_button(
                "📅 Export itinerary",
                data=ics_bytes,
                file_name=f"trip-{_latest_trip['trip_id']}.ics",
                mime="text/calendar",
                key="ics_download_top",
                use_container_width=True,
            )

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
