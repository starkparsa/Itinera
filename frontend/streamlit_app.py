import os
import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="AI Travel Planner", page_icon="🧭")
st.title("🧭 AI Travel Planner")
st.caption("Describe a trip and get a day-by-day itinerary.")

if "trips" not in st.session_state:
    st.session_state.trips = []  # local history for this session

prompt = st.chat_input("e.g. 4 days in Lisbon, love food and walking, mid-range budget")

if prompt:
    with st.spinner("Planning your trip..."):
        try:
            res = requests.post(
                f"{BACKEND_URL}/trips/generate",
                json={"prompt": prompt},
                timeout=180,
            )
            res.raise_for_status()
            st.session_state.trips.append(res.json())
        except requests.exceptions.RequestException as exc:
            st.error(f"Couldn't reach the planner backend: {exc}")

for trip in reversed(st.session_state.trips):
    st.subheader(f"📍 {trip['destination']}")
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
    st.divider()
