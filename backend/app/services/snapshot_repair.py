
from copy import deepcopy
from typing import Any, Iterable


def repair_snapshot_bullets(
    snapshot: dict[str, Any],
    profile: dict[str, Any],
    *,
    profile_sha256: str,
    fact_ids: Iterable[str],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """
    Build a separate candidate snapshot.

    For explicitly selected fact IDs, replace
    generated bullet claims with the original
    master-profile fact descriptions.

    This does NOT approve the resume.
    """

    targets = list(fact_ids)

    if (
        not targets
        or len(targets) != len(set(targets))
    ):
        raise ValueError(
            "Provide unique, nonempty fact IDs."
        )

    if (
        snapshot.get("profile_sha256")
        != profile_sha256
    ):
        raise ValueError(
            "Snapshot/profile SHA-256 mismatch."
        )

    if snapshot.get("quality_passed") is not False:
        raise ValueError(
            "Expected an evaluated, failed "
            "snapshot for repair."
        )

    selected = snapshot.get(
        "selected_fact_ids"
    )

    if (
        not isinstance(selected, list)
        or len(selected) != len(set(selected))
    ):
        raise ValueError(
            "Invalid selected_fact_ids "
            "in snapshot."
        )

    if not set(targets).issubset(selected):
        raise ValueError(
            "Requested fact ID was not selected "
            "in the saved run."
        )

    # Index original facts by BOTH
    # work ID and fact ID.
    sources: dict[
        tuple[str, str], str
    ] = {}

    all_ids: set[str] = set()

    for work in profile.get(
        "work_items", []
    ):
        work_id = work.get("id")

        for fact in work.get("facts", []):
            fact_id = fact.get("id")
            description = fact.get("description")

            if (
                not work_id
                or not fact_id
                or not isinstance(
                    description, str
                )
            ):
                raise ValueError(
                    "Invalid work/fact evidence "
                    "in master profile."
                )

            if fact_id in all_ids:
                raise ValueError(
                    "Duplicate source fact ID: "
                    f"{fact_id}"
                )

            all_ids.add(fact_id)

            sources[
                (work_id, fact_id)
            ] = description.strip()

    # Copy the snapshot instead of modifying
    # the original Python dictionary.
    candidate = deepcopy(snapshot)

    document = candidate.get(
        "resume_document"
    )

    if (
        not isinstance(document, dict)
        or not isinstance(
            document.get("entries"), list
        )
    ):
        raise ValueError(
            "Snapshot has no structured "
            "ResumeDocument entries."
        )

    seen: set[str] = set()
    changes: list[dict[str, str]] = []

    for entry in document["entries"]:
        work_id = entry.get("work_id")

        for bullet in entry.get(
            "bullets", []
        ):
            fact_id = bullet.get("fact_id")

            if fact_id not in targets:
                continue

            if fact_id in seen:
                raise ValueError(
                    "Fact ID appears in multiple "
                    f"bullets: {fact_id}"
                )

            seen.add(fact_id)

            # Check this fact belongs to
            # the specific work item.
            source_text = sources.get(
                (work_id, fact_id)
            )

            if (
                not source_text
                or len(source_text) < 10
            ):
                raise ValueError(
                    "Source fact does not belong "
                    f"to {work_id}: {fact_id}"
                )

            old_text = bullet.get("text")

            if not isinstance(old_text, str):
                raise ValueError(
                    "Invalid original bullet "
                    f"text: {fact_id}"
                )

            bullet["text"] = source_text

            changes.append({
                "work_id": work_id,
                "fact_id": fact_id,
                "before": old_text,
                "after": source_text,
            })

    missing = set(targets) - seen

    if missing:
        raise ValueError(
            "Requested facts not present "
            "as resume bullets: "
            f"{sorted(missing)}"
        )

    if all(
        change["before"] == change["after"]
        for change in changes
    ):
        raise ValueError(
            "All requested bullets already "
            "equal their source facts."
        )

    # Never claim approval after editing.
    candidate["quality_passed"] = False
    candidate["run_status"] = (
        "needs_revalidation"
    )

    candidate[
        "previous_evaluation_feedback"
    ] = snapshot.get(
        "evaluation_feedback"
    )

    candidate["evaluation_feedback"] = (
        "Source-fact bullet corrections applied; "
        "full semantic re-evaluation required."
    )

    return candidate, changes
    