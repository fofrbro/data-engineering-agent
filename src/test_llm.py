from src.llm import client


response = client.responses.create(
    model="gpt-5.6",
    input="Explique en une phrase ce qu'est un Lakehouse."
)

print(response.output_text)
