
from openai import OpenAI


class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            base_url="http://127.0.0.1:8000/v1",
            api_key="antigravity-local",
            timeout=120.0,
            max_retries=1,
        )
        self.model = "gpt-4o"

    def generate(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        content = response.choices[0].message.content

        if not content:
            raise ValueError("LLM returned empty response")

        return content


if __name__ == "__main__":
    llm = LLMClient()
    print(llm.generate("Explain LangGraph in one sentence."))
