import streamlit as st
import requests

st.title("AI Travel Planner")
destination = st.chat_input("Where do you want to go, and for how long?")

if destination:
    with st.spinner("Planning your trip..."):
        res = requests.post("http://localhost:8000/trips/generate", json={"prompt": destination})
        st.write(res.json()["itinerary"])