
from backend.app.models.profile import MasterProfile
from backend.app.agents.jd_analyzer import JobAnalysis


def retrieve_facts(
    profile: MasterProfile,
    job: JobAnalysis,
    limit: int = 8
) -> list[str]:

    required = {s.lower() for s in job.required_skills}
    preferred = {s.lower() for s in job.preferred_skills}

    ranked = []

    for work in profile.work_items:
        for fact in work.facts:
            skills = {s.lower() for s in fact.skills}

            score = (
                len(skills & required) * 3
                + len(skills & preferred)
            )

            if score > 0:
                ranked.append((score, fact.id))

    ranked.sort(key=lambda x: x[0], reverse=True)

    return [fact_id for _, fact_id in ranked[:limit]]
