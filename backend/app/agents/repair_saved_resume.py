
import argparse
import hashlib
import json

from pathlib import Path

from backend.app.models.resume_document import (
    ResumeDocument,
)
from backend.app.services.profile_store import (
    PROFILE_PATH,
)
from backend.app.services.snapshot_repair import (
    repair_snapshot_bullets,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Repair selected resume bullets using "
            "exact master-profile source facts."
        )
    )

    parser.add_argument(
        "--snapshot",
        default=(
            ".cache/resume_pipeline/"
            "last_resume_run.json"
        ),
    )

    parser.add_argument(
        "--output",
        default=(
            ".cache/resume_pipeline/"
            "grounded_candidate.json"
        ),
    )

    parser.add_argument(
        "--fact-ids",
        nargs="+",
        required=True,
        help=(
            "Exact source fact IDs to restore "
            "in generated bullets"
        ),
    )

    args = parser.parse_args()

    snapshot_path = Path(args.snapshot)
    output_path = Path(args.output)

    if not snapshot_path.is_file():
        raise FileNotFoundError(
            f"Snapshot missing: {snapshot_path}"
        )

    if (
        snapshot_path.resolve()
        == output_path.resolve()
    ):
        raise ValueError(
            "Cannot overwrite the original snapshot."
        )

    if output_path.exists():
        raise FileExistsError(
            f"Candidate already exists: {output_path}"
        )

    # Use the exact career profile file
    # from which the LangGraph run was built.
    profile_bytes = PROFILE_PATH.read_bytes()

    profile_hash = hashlib.sha256(
        profile_bytes
    ).hexdigest()

    profile = json.loads(
        profile_bytes.decode("utf-8-sig")
    )

    snapshot = json.loads(
        snapshot_path.read_text(
            encoding="utf-8"
        )
    )

    candidate, changes = repair_snapshot_bullets(
        snapshot,
        profile,
        profile_sha256=profile_hash,
        fact_ids=args.fact_ids,
    )

    # Validate the complete updated
    # ResumeDocument against its Pydantic schema.
    ResumeDocument.model_validate(
        candidate["resume_document"]
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            candidate,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n--- GROUNDED BULLET REPAIR ---")

    for change in changes:
        print(
            "\nWork:",
            change["work_id"],
        )

        print(
            "Fact:",
            change["fact_id"],
        )

        print(
            "BEFORE:",
            change["before"],
        )

        print(
            "AFTER: ",
            change["after"],
        )

    print(
        "\nCorrected bullets:",
        len(changes),
    )

    print(
        "Candidate snapshot:",
        output_path,
    )

    print(
        "Evaluator status: NOT PASSED. "
        "Re-evaluation is required."
    )


if __name__ == "__main__":
    main()
