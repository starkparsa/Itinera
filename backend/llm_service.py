import requests

def generate_itinerary(prompt: str) -> str:
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": "llama3.1", "prompt": prompt, "stream": False}
    )
    return response.json()["response"]