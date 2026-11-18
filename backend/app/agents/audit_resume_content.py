
"""Read-only content audit CLI. No LLM and no DOCX editing."""

import argparse
from pathlib import Path

from backend.app.services.resume_content_audit import (
    audit_resume_content,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Audit approved resume coverage "
            "and JD evidence hints"
        )
    )

    parser.add_argument(
        "--source",
        required=True,
        help="Assembled DOCX after insertion/removal",
    )

    parser.add_argument(
        "--snapshot",
        default=(
            ".cache/resume_pipeline/"
            "approved_resume_run_v3.json"
        ),
    )

    parser.add_argument(
        "--profile",
        default="data/master_profile.json",
    )

    jd = parser.add_mutually_exclusive_group()

    jd.add_argument(
        "--jd-file",
        help="UTF-8 text file containing the exact JD",
    )

    jd.add_argument(
        "--jd-text",
        help="Direct job description text",
    )

    parser.add_argument(
        "--output",
        default="outputs/content_audit_report.json",
    )

    args = parser.parse_args()

    description = (
        Path(args.jd_file).read_text(
            encoding="utf-8-sig"
        )
        if args.jd_file
        else args.jd_text
    )

    report = audit_resume_content(
        source_path=args.source,
        snapshot_path=args.snapshot,
        profile_path=args.profile,
        job_description=description,
    )

    destination = Path(args.output)

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )

    print(
        "\n--- READ-ONLY RESUME CONTENT AUDIT ---"
    )

    print(
        "Approved work entries:",
        len(report.approved_work_ids),
    )

    print(
        "Fully accounted for:",
        sum(
            entry.status == "pass"
            for entry in report.entries
        ),
    )

    print(
        "Need heading/role review:",
        sum(
            entry.status == "review"
            for entry in report.entries
        ),
    )

    print(
        "Failed entry checks:",
        sum(
            entry.status == "fail"
            for entry in report.entries
        ),
    )

    print(
        "Retriever-selected facts omitted:",
        len(report.omitted_selected_facts),
    )

    print(
        "Retained template-only candidates:",
        len(report.retained_template_entries),
    )

    print(
        "JD relevance hints:",
        len(
            report.potentially_relevant_unselected_facts
        ),
    )

    print(
        "JD provided:",
        report.jd_relevance_reviewed,
    )

    for entry in report.entries:
        print(
            f"[{entry.status.upper()}] "
            f"{entry.work_id} — "
            f"{entry.matched_bullets}/"
            f"{entry.expected_bullets} bullets"
        )

        for note in entry.notes:
            print("  NOTE:", note)

    for error in report.errors:
        print("ERROR:", error)

    for warning in report.warnings:
        print("WARNING:", warning)

    print(
        "Approved content complete:",
        report.approved_content_complete,
    )

    print("Report:", destination)

    print(
        "NOT FINAL APPROVAL: layout and "
        "template-only content need separate QA."
    )


if __name__ == "__main__":
    main()
