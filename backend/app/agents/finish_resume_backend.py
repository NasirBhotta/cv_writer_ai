
import argparse
import json

from backend.app.services.snapshot_semantic_recheck import (
    load_candidate_for_recheck,
    semantic_recheck_and_save,
)
from backend.app.services.dynamic_resume_preview import (
    write_dynamic_resume_preview,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Complete resume backend operations "
            "without rerunning LangGraph writer."
        )
    )

    subparsers = parser.add_subparsers(
        dest="operation",
        required=True,
    )

    check = subparsers.add_parser(
        "recheck"
    )

    check.add_argument(
        "--snapshot",
        default=(
            ".cache/resume_pipeline/"
            "grounded_candidate.json"
        ),
    )

    check.add_argument(
        "--output",
        default=(
            ".cache/resume_pipeline/"
            "approved_resume_run.json"
        ),
    )

    check.add_argument(
        "--semantic",
        action="store_true",
        help=(
            "Run exactly one LLM semantic "
            "verification request."
        ),
    )

    preview = subparsers.add_parser(
        "preview"
    )

    preview.add_argument(
        "--template",
        required=True,
    )

    preview.add_argument(
        "--snapshot",
        default=(
            ".cache/resume_pipeline/"
            "approved_resume_run.json"
        ),
    )

    preview.add_argument(
        "--output",
        default=(
            "outputs/dynamic_resume_preview.docx"
        ),
    )

    args = parser.parse_args()

    if args.operation == "recheck":
        if args.semantic:
            result = semantic_recheck_and_save(
                args.snapshot,
                args.output,
            )

            print(
                json.dumps(
                    result,
                    ensure_ascii=False,
                    indent=2,
                )
            )

        else:
            _, payload = load_candidate_for_recheck(
                args.snapshot
            )

            print("OFFLINE VALIDATION PASSED")

            print(
                "Bullets checked structurally:",
                len(payload["bullets"]),
            )

            print(
                "No LLM called; "
                "quality_passed has NOT changed."
            )

    else:
        result = write_dynamic_resume_preview(
            args.template,
            args.snapshot,
            args.output,
        )

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )

        print(
            "PREVIEW ONLY: original template "
            "unchanged; layout and human "
            "review still required."
        )


if __name__ == "__main__":
    main()
