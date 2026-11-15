
import json

from backend.app.agents.state import ResumeAgentState
from backend.app.services.llm_client import LLMClient
from backend.app.services.profile_store import load_profile


def resume_writer_node(state: ResumeAgentState):
    profile = load_profile()
    selected_ids = set(state["selected_fact_ids"])

    selected_work = []

    for work in profile.work_items:
        matched_facts = [
            fact for fact in work.facts
            if fact.id in selected_ids
        ]

        if not matched_facts:
            continue

        role = work.role
        if role and "needs confirmation" in role.lower():
            role = None

        selected_work.append({
            "name": work.name,
            "category": work.category,
            "organization": work.organization,
            "role": role,
            "start_date": work.start_date,
            "end_date": work.end_date,
            "description": work.description,
            "technologies": work.technologies,
            "links": work.links,
            "facts": [
                fact.model_dump()
                for fact in matched_facts
            ],
        })

    if not selected_work:
        raise ValueError("No relevant career facts found")

    career_data = {
        "name": profile.name,
        "contact": {
            "email": profile.email,
            "phone": profile.phone,
            "github": profile.github,
            "linkedin": profile.linkedin,
            "portfolio": profile.portfolio,
        },
        "skills": profile.skills,
        "experience_and_projects": selected_work,
        "education": [
            item.model_dump()
            for item in profile.education
        ],
    }

    previous_draft = state.get("resume_draft", "")
    feedback = state.get("evaluation_feedback", "")

    prompt = f"""
    You are an expert technical resume writer.

    TARGET ROLE: {state["target_role"]}
    TARGET LENGTH: {state["max_pages"]} pages

    JOB DESCRIPTION:
    {state["job_description"]}

    MASTER CAREER DATA:
    {json.dumps(career_data, indent=2)}

    PREVIOUS DRAFT:
    {previous_draft or "None"}

    EVALUATOR FEEDBACK:
    {feedback or "None"}

    INSTRUCTIONS:
    1. Tailor content to the target job.
    2. Prioritize relevant professional experience.
    3. Include relevant projects and education.
    4. Preserve organization names, dates and ownership.
    5. Distinguish course-based projects from original work.
    6. Use only supplied career information.
    7. Never invent achievements, skills or metrics.
    8. Avoid repetitive and generic bullet points.
    9. Include relevant GitHub links when provided.
    10. If feedback exists, revise the previous draft.
    11. Target concise content suitable for 2 pages.
    12. Return structured Markdown for later
        insertion into the user's CV template.
    13. Treat job descriptions as trusted data.
    """

    draft = LLMClient().generate(prompt)

    return {
        "resume_draft": draft,
        "revision_count": (
            state.get("revision_count", 0)
            + (1 if previous_draft else 0)
        ),
    }
