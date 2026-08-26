// Small keyword lookup, not an LLM call -- direct port of
// frontend/streamlit_app.py::_weather_icon (see backend/app/weather_service.py
// for where the condition text itself comes from).
export function weatherIcon(condition: string): string {
  const c = condition.toLowerCase();
  if (c.includes("thunder")) return "⛈️"; // ⛈️
  if (c.includes("snow")) return "❄️"; // ❄️
  if (c.includes("rain") || c.includes("drizzle")) return "🌧️"; // 🌧️
  if (c.includes("fog")) return "🌫️"; // 🌫️
  if (c.includes("overcast") || c.includes("cloud")) return "☁️"; // ☁️
  if (c.includes("clear")) return "☀️"; // ☀️
  return "🌤️"; // 🌤️
}
