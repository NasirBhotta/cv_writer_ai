
import argparse
from pathlib import Path

from backend.app.services.saved_resume_preview import (
    prepare_saved_resume_preview,
    write_saved_resume_preview,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare a zero-LLM DOCX preview "
            "from a saved resume run"
        )
    )

    parser.add_argument(
        "--template",
        required=True,
        help="User's original DOCX template",
    )

    parser.add_argument(
        "--snapshot",
        default=(
            ".cache/resume_pipeline/"
            "last_resume_run.json"
        ),
        help="Previously saved LangGraph result",
    )

    parser.add_argument(
        "--report",
        default=(
            ".cache/resume_pipeline/"
            "last_preview_manifest.json"
        ),
        help="Where to save preview analysis JSON",
    )

    parser.add_argument(
        "--write-preview",
        action="store_true",
        help=(
            "Write a DOCX preview only when "
            "saved evaluation passed"
        ),
    )

    parser.add_argument(
        "--output",
        default="outputs/saved_resume_preview.docx",
        help=(
            "New DOCX output path; existing "
            "files will not be overwritten"
        ),
    )

    args = parser.parse_args()

    # Analyze without modifying the DOCX.
    prepared = prepare_saved_resume_preview(
        args.template,
        args.snapshot,
    )

    manifest = prepared.manifest

    # Save analysis for inspection and debugging.
    report_path = Path(args.report)

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )

    print(
        "\n--- SAVED RUN → ORIGINAL TEMPLATE ---"
    )

    print(
        "Evaluator passed:",
        manifest.quality_passed,
    )

    print(
        "Summary mapped:",
        manifest.summary_included,
    )

    print(
        "Safe paragraph edits:",
        len(manifest.planned_block_ids),
    )

    print(
        "Matched work IDs:",
        manifest.updated_work_ids,
    )

    print(
        "Skipped generated entries:",
        len(manifest.skipped_entries),
    )

    print(
        "Unchanged template entries:",
        len(manifest.unchanged_template_entries),
    )

    for issue in manifest.skipped_entries:
        print("SKIPPED:", issue)

    for warning in manifest.warnings:
        print("WARNING:", warning)

    print(
        "Preview analysis:",
        report_path,
    )

    if args.write_preview:
        output = write_saved_resume_preview(
            prepared,
            args.output,
        )

        print("PREVIEW DOCX:", output)

        print(
            "PREVIEW ONLY: "
            "not approved for job applications."
        )

    else:
        print(
            "Dry-run only: no DOCX was written."
        )


if __name__ == "__main__":
    main()
