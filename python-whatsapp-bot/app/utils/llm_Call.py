import openai
import os


client = openai.OpenAI(api_key=OPENAI_API_KEY)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Tell me about OpenAI."}
    ],
    temperature=0.7,
    max_tokens=200
)

print(response.choices[0].message.content)
