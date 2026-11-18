
import json
import re

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from backend.app.models.resume_document import (
    ResumeDocument,
)
from backend.app.services.career_context import (
    build_career_context,
)
from backend.app.services.career_validator import (
    validate_career_context,
    validate_resume_draft,
)
from backend.app.services.profile_store import (
    PROFILE_PATH,
    load_profile,
)
from backend.app.services.resume_grounding import (
    validate_resume_document,
)
from backend.app.services.resume_renderer import (
    render_resume_document,
)


def document_hash(document: dict) -> str:
    canonical = json.dumps(
        document,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def load_candidate_for_recheck(
    snapshot_path: str | Path,
) -> tuple[dict, dict]:
    """
    Run deterministic validation without an LLM.

    Returns:
        Original snapshot and semantic-review payload.
    """

    snapshot = json.loads(
        Path(snapshot_path).read_text(
            encoding="utf-8"
        )
    )

    actual_hash = sha256(
        PROFILE_PATH.read_bytes()
    ).hexdigest()

    if (
        actual_hash
        != snapshot.get("profile_sha256")
    ):
        raise ValueError(
            "Master profile hash mismatch; "
            "saved evidence is stale."
        )

    ids = snapshot.get(
        "selected_fact_ids"
    )

    if (
        not isinstance(ids, list)
        or not ids
        or len(ids) != len(set(ids))
    ):
        raise ValueError(
            "Invalid selected career fact IDs."
        )

    profile = load_profile()

    document = ResumeDocument.model_validate(
        snapshot["resume_document"]
    )

    context = build_career_context(
        profile,
        ids,
    )

    errors = validate_career_context(
        context
    )

    errors.extend(
        validate_resume_document(
            document,
            context,
        )
    )

    if errors:
        raise ValueError(
            "Deterministic grounding errors: "
            + "; ".join(errors)
        )

    draft = render_resume_document(
        document,
        context,
    )

    errors = validate_resume_draft(
        draft,
        context,
    )

    if errors:
        raise ValueError(
            "Resume structure errors: "
            + "; ".join(errors)
        )

    # Authoritative source facts indexed by
    # the work item AND fact identifier.
    evidence = {}

    for work in profile.work_items:
        for fact in work.facts:
            evidence[
                (work.id, fact.id)
            ] = fact.description

    bullets = []

    for entry in document.entries:
        for bullet in entry.bullets:
            source = evidence.get(
                (
                    entry.work_id,
                    bullet.fact_id,
                )
            )

            if (
                not source
                or bullet.fact_id not in ids
            ):
                raise ValueError(
                    "Unknown or unselected "
                    "bullet source fact."
                )

            bullets.append({
                "work_id": entry.work_id,
                "fact_id": bullet.fact_id,
                "source_fact": source,
                "candidate_bullet": bullet.text,
            })

    review_payload = {
        "headline": document.headline,
        "summary": document.summary,
        "skills_in_profile": profile.skills,
        "selected_sources": [
            {
                "work_id": work_id,
                "fact_id": fact_id,
                "description": description,
            }
            for (
                work_id,
                fact_id
            ), description in evidence.items()
            if fact_id in ids
        ],
        "bullets": bullets,
    }

    return snapshot, review_payload


def semantic_recheck_and_save(
    snapshot_path: str | Path,
    output_path: str | Path,
) -> dict:
    """
    Make one LLM semantic-review call.

    Only a passing review can produce an
    approved snapshot. Never overwrite input.
    """

    source = Path(snapshot_path)
    output = Path(output_path)

    if source.resolve() == output.resolve():
        raise ValueError(
            "Cannot overwrite source snapshot."
        )

    if output.exists():
        raise FileExistsError(
            f"Output already exists: {output}"
        )

    snapshot, payload = (
        load_candidate_for_recheck(source)
    )

    checked = [
        item["fact_id"]
        for item in payload["bullets"]
    ]

    prompt = (
        "You are a strict CV evidence reviewer. "
        "Verify EVERY candidate bullet against its "
        "exact source_fact. Do not infer technologies, "
        "outcomes, implementation details or metrics "
        "from adjacent metadata. Verify headline "
        "and summary against ALL selected_sources "
        "and skills_in_profile. Accept accurate, "
        "conservative paraphrases. "
        "Return ONLY one JSON object with keys: "
        "passed (boolean), checked_fact_ids "
        "(array of strings, one ID per bullet in "
        "the same order), and issues "
        "(array of strings). "
        "If uncertain, passed=false and explain "
        "the issue. Do not omit any bullet.\n\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
        )
    )

    # Import lazily: offline validation must
    # never initialize the LLM client.
    from backend.app.services.llm_client import (
        LLMClient,
    )

    response = LLMClient().generate(
        prompt
    ).strip()

    response = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        response,
    ).strip()

    try:
        verdict = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "Semantic recheck returned invalid JSON; "
            "resume was not approved."
        ) from exc

    if (
        not isinstance(verdict, dict)
        or not isinstance(
            verdict.get("passed"), bool
        )
    ):
        raise ValueError(
            "Invalid semantic verdict schema."
        )

    issues = verdict.get("issues")

    if (
        not isinstance(issues, list)
        or not all(
            isinstance(issue, str)
            for issue in issues
        )
    ):
        raise ValueError(
            "Invalid semantic issues field."
        )

    if (
        verdict.get("checked_fact_ids")
        != checked
    ):
        raise ValueError(
            "Semantic recheck did not verify "
            "every generated bullet."
        )

    if verdict["passed"] and issues:
        raise ValueError(
            "Inconsistent verdict: "
            "passed with issues."
        )

    approved = verdict["passed"] is True

    candidate = deepcopy(snapshot)

    candidate["quality_passed"] = approved

    candidate["run_status"] = (
        "rechecked_approved"
        if approved
        else "rechecked_rejected"
    )

    candidate["evaluation_feedback"] = (
        "Independent saved-document "
        "semantic review passed."
        if approved
        else "; ".join(issues)
    )

    candidate["semantic_recheck"] = {
        "passed": approved,
        "issues": issues,
        "checked_fact_ids": checked,
        "document_sha256": document_hash(
            candidate["resume_document"]
        ),
    }

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        json.dumps(
            candidate,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "passed": approved,
        "issues": issues,
        "output": str(output),
    }
