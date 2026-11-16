
import re
from typing import Any

from backend.app.models.resume_document import ResumeDocument


EXPERIENCE_CATEGORIES = {
    "employment",
    "experience",
    "internship",
    "job",
    "work",
    "professional",
    "contract",
    "freelance",
}


def _expected_section(work: dict[str, Any]) -> str | None:
    category = str(work.get("category") or "").casefold()
    role = str(work.get("role") or "").casefold()
    name = str(work.get("name") or "").casefold()

    category_words = set(
        re.findall(r"[a-z]+", category)
    )

    if (
        category_words & EXPERIENCE_CATEGORIES
        or "intern" in role
        or re.search(r"\bintern(?:ship)?\b", name)
    ):
        return "experience"

    if category_words & {
        "project", "product", "capstone"
    }:
        return "project"

    # Unknown category: don't guess.
    return None


def validate_resume_document(
    document: ResumeDocument,
    context: dict[str, Any],
) -> list[str]:

    errors = []

    work_lookup = {
        work["id"]: work
        for work in context["work_items"]
    }

    allowed_skills = {
        skill.strip().casefold()
        for skill in context["candidate"].get("skills", [])
        if isinstance(skill, str)
    }

    selected_ids = set(
        context["selected_fact_ids"]
    )

    used_work_ids = set()
    used_fact_ids = set()

    # Validate technical skills.
    for group in document.skill_groups:
        for skill in group.skills:
            if skill.strip().casefold() not in allowed_skills:
                errors.append(
                    f"Unknown profile skill: {skill}"
                )

    # Validate every resume entry.
    for entry in document.entries:
        if entry.work_id in used_work_ids:
            errors.append(
                f"Duplicate work entry: {entry.work_id}"
            )

        used_work_ids.add(entry.work_id)

        work = work_lookup.get(entry.work_id)

        if work is None:
            errors.append(
                f"Unknown work ID: {entry.work_id}"
            )
            continue

        expected = _expected_section(work)

        if expected and entry.section != expected:
            errors.append(
                f"Wrong section for {entry.work_id}: "
                f"expected {expected}, got {entry.section}"
            )

        allowed_fact_ids = {
            fact["id"]
            for fact in work["selected_facts"]
        }

        for bullet in entry.bullets:
            if bullet.fact_id in used_fact_ids:
                errors.append(
                    f"Reused career fact: {bullet.fact_id}"
                )

            used_fact_ids.add(bullet.fact_id)

            if bullet.fact_id not in selected_ids:
                errors.append(
                    f"Fact was not selected: {bullet.fact_id}"
                )

            if bullet.fact_id not in allowed_fact_ids:
                errors.append(
                    f"Fact {bullet.fact_id} does not "
                    f"belong to {entry.work_id}"
                )

    # Require relevant professional experience
    # when professional evidence is available.
    professional_work_ids = {
        work["id"]
        for work in context["work_items"]
        if _expected_section(work) == "experience"
    }

    required = min(2, len(professional_work_ids))

    included = len(
        professional_work_ids & {
            entry.work_id
            for entry in document.entries
            if entry.section == "experience"
        }
    )

    if included < required:
        errors.append(
            "Insufficient professional experience: "
            f"{included}/{required} relevant entries"
        )

    return errors


def build_grounding_pairs(
    document: ResumeDocument,
    context: dict[str, Any],
) -> list[dict[str, str]]:
    """
    Link each generated bullet to its original source fact.

    Call validate_resume_document() first.
    """

    work_lookup = {
        work["id"]: work
        for work in context["work_items"]
    }

    pairs = []

    for entry in document.entries:
        work = work_lookup[entry.work_id]

        fact_lookup = {
            fact["id"]: fact
            for fact in work["selected_facts"]
        }

        for bullet in entry.bullets:
            source = fact_lookup[bullet.fact_id]

            pairs.append({
                "work_id": entry.work_id,
                "work_name": work["name"],
                "role": str(work.get("role") or ""),
                "category": str(
                    work.get("category") or ""
                ),
                "fact_id": bullet.fact_id,
                "source_fact": source["description"],
                "generated_bullet": bullet.text,
            })

    return pairs
