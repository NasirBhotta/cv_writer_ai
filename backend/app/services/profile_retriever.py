
import json

from pydantic import BaseModel, Field

from backend.app.models.profile import MasterProfile
from backend.app.agents.jd_analyzer import JobAnalysis
from backend.app.services.llm_client import LLMClient


class FactSelection(BaseModel):
    fact_ids: list[str] = Field(default_factory=list)


def retrieve_facts(
    profile: MasterProfile,
    job: JobAnalysis,
    limit: int = 18,
) -> list[str]:

    career_facts = []
    valid_ids = set()

    for work in profile.work_items:
        for fact in work.facts:
            valid_ids.add(fact.id)

            career_facts.append({
                "id": fact.id,
                "project": work.name,
                "category": work.category,
                "role": work.role,
                "technologies": work.technologies,
                "description": fact.description,
                "skills": fact.skills,
            })

    if not career_facts:
        return []

    prompt = f"""
    You are an expert AI career-matching agent.

    JOB ANALYSIS:
    {job.model_dump_json(indent=2)}

    AVAILABLE CAREER FACTS:
    {json.dumps(career_facts, indent=2)}

    TASK:
    Select {limit} relevant career facts for a
    professional two-page resume, when available.

    SELECTION STRATEGY:
    1. Analyze the complete job requirements.
    2. Prioritize relevant professional employment
    and internships.
    3. Include relevant independent commercial projects.
    4. Include strong AI and Flutter projects.
    5. Consider technical depth and measurable impact.
    6. Prefer coverage across multiple work experiences.
    7. For hybrid roles, balance AI, backend and Flutter.
    8. Do not select facts just to fill a quota.
    9. Return existing fact IDs only.
    10. Rank IDs by relevance to the job.

    IMPORTANT:
    Do not select only one project when multiple
    relevant professional experiences exist.

    Return ONLY JSON matching:
    {json.dumps(FactSelection.model_json_schema())}
    """

    response = LLMClient().generate(prompt).strip()

    if response.startswith("```"):
        response = response.split("\n", 1)[1]
        response = response.rsplit("```", 1)[0].strip()

    selection = FactSelection.model_validate_json(response)

    # Preserve ranking, remove duplicates and invalid IDs
    selected = []
    seen = set()

    for fact_id in selection.fact_ids:
        if fact_id in valid_ids and fact_id not in seen:
            selected.append(fact_id)
            seen.add(fact_id)

        if len(selected) >= limit:
            break

    if not selected:
        raise ValueError("LLM selected no valid career facts")

    print(f"Total available facts: {len(career_facts)}")
    print(f"LLM selected: {len(selected)} facts")
    print(f"Selected IDs: {selected}")
    return selected
