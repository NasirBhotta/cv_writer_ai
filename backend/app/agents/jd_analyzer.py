
import json
from typing import Literal

from pydantic import BaseModel, Field
from backend.app.services.llm_client import LLMClient


# Structured output schema
class JobAnalysis(BaseModel):
    job_title: str
    seniority: Literal[
        "intern", "junior", "mid", "senior", "unknown"
    ] = "unknown"
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


def analyze_job(jd: str) -> JobAnalysis:
    if not jd.strip():
        raise ValueError("Job description cannot be empty")

    schema = json.dumps(JobAnalysis.model_json_schema())

    prompt = f"""
    You are a job description analysis agent.

    Extract job requirements accurately.
    Do not invent missing information.
    Return ONLY valid JSON matching this schema:
    {schema}

    JOB DESCRIPTION:
    {jd}
    """

    llm = LLMClient()
    response = llm.generate(prompt).strip()

    # Handle markdown code fences if the LLM adds them
    if response.startswith("```"):
        response = response.split("\n", 1)[1]
        response = response.rsplit("```", 1)[0].strip()

    return JobAnalysis.model_validate_json(response)


if __name__ == "__main__":
    jd = """
    We are hiring a Junior AI Engineer.
    Required: Python, FastAPI, RAG and REST APIs.
    LangGraph experience is a plus.
    Responsibilities include building AI agents
    and integrating backend services.
    """

    result = analyze_job(jd)
    print(result.model_dump_json(indent=2))
