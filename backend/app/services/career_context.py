
import json
from typing import Any

from backend.app.models.profile import MasterProfile


def build_career_context(
    profile: MasterProfile,
    selected_fact_ids: list[str],
) -> dict[str, Any]:
    """
    Build a shared evidence context for Writer and Evaluator.

    Only selected facts are included as project achievements.
    Profile metadata is preserved without inventing details.
    """

    if not selected_fact_ids:
        raise ValueError("No career facts selected")

    # Preserve the LLM's ranking and remove duplicate IDs.
    ordered_ids = list(dict.fromkeys(selected_fact_ids))
    requested_ids = set(ordered_ids)
    ranking = {
        fact_id: index
        for index, fact_id in enumerate(ordered_ids)
    }

    selected_work_items = []
    found_ids = set()

    for work in profile.work_items:
        matched_facts = [
            fact
            for fact in work.facts
            if fact.id in requested_ids
        ]

        if not matched_facts:
            continue

        matched_facts.sort(
            key=lambda fact: ranking[fact.id]
        )

        found_ids.update(fact.id for fact in matched_facts)

        # Preserve project details while excluding unselected facts.
        work_data = work.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"facts"},
        )

        work_data["selected_facts"] = [
            fact.model_dump(
                mode="json",
                exclude_none=True,
            )
            for fact in matched_facts
        ]

        selected_work_items.append(work_data)

    # Never silently accept nonexistent fact IDs.
    unknown_ids = requested_ids - found_ids

    if unknown_ids:
        raise ValueError(
            f"Unknown career fact IDs: {sorted(unknown_ids)}"
        )

    # Order projects by the highest-ranked selected fact.
    selected_work_items.sort(
        key=lambda work: min(
            ranking[fact["id"]]
            for fact in work["selected_facts"]
        )
    )

    # Candidate details include skills, education and contact links.
    # Work items are handled separately to prevent leaking
    # unselected achievements into the writing context.
    candidate = profile.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"work_items"},
    )

    return {
        "candidate": candidate,
        "selected_fact_ids": ordered_ids,
        "work_items": selected_work_items,
    }


def career_context_to_json(
    context: dict[str, Any],
) -> str:
    return json.dumps(
        context,
        ensure_ascii=False,
        indent=2,
    )
