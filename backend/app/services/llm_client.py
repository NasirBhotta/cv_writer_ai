
import logging

from openai import APIStatusError, OpenAI


logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            base_url="http://127.0.0.1:8001/v1",
            api_key="antigravity-local",
            timeout=120.0,
            max_retries=3,
        )
        self.model = "gpt-4o"

    def generate(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Spend at most 30 seconds thinking before responding. "
                            "Do not think for longer than 30 seconds; provide your "
                            "best answer within that thinking budget. "
                            "Follow the requested output format."
                        ),
                    },
                    {"role": "user", "content": prompt}
                ],
            )
        except APIStatusError as exc:
            logger.error(
                "LLM request failed after SDK retries: endpoint=%s status=%s body=%s",
                self.client.base_url,
                exc.status_code,
                exc.response.text[:2000],
            )
            raise

        content = response.choices[0].message.content

        if not content:
            raise ValueError("LLM returned empty response")

        return content


if __name__ == "__main__":
    llm = LLMClient()
    print(llm.generate("Explain LangGraph in one sentence."))
