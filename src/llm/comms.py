import os 
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL")

client = OpenAI(
    api_key=API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

def send_message(messages):
    if not messages:
        raise ValueError("Messages cannot be empty.")

    try:
        print(f"Sending msg to: {MODEL}")
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages
        )
        usage = response.usage
        if usage:
            print("Input tokens:", usage.prompt_tokens)
            print("Output tokens:", usage.completion_tokens)
            print("Total tokens:", usage.total_tokens)
        return response.choices[0].message.content

    except Exception as e:
        raise RuntimeError(f"Chud Gaye Shyd: {e}") from e

messages = [
    {
        "role": "system",
        "content": "You are a professional cybersecurity assistant."
    },
    {
        "role": "user",
        "content": "Tell me the OSWP Top 10 vulnerabilities for websites."
    }
]

print(send_message(messages))