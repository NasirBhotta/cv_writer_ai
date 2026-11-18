
"""Resume CLI: fresh JD generation or existing approved-snapshot assembly.

Legacy usage without an explicit mode remains snapshot mode.
"""

import argparse
import sys
from pathlib import Path

from backend.app.models.page_layout_policy import PageRequirements
from backend.app.models.resume_pipeline_result import (
    ContinuationHeaderChoice,
    FreshResumeRequest,
    InsertionChoice,
    RemovalChoice,
    ResumeAssemblyRequest,
)
from backend.app.services.profile_store import PROFILE_PATH
from backend.app.services.resume_pipeline_orchestrator import (
    assemble_resume,
    generate_resume_from_jd,
)


def _parser(mode: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Fresh JD-to-PDF mode" if mode == "fresh"
            else "Approved snapshot-to-PDF mode"
        )
    )
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--converter",
        choices=("auto", "word", "libreoffice"),
        default="auto",
    )
    parser.add_argument("--no-images", action="store_true")

    jd = parser.add_mutually_exclusive_group()
    jd.add_argument("--jd-file", type=Path)
    jd.add_argument("--jd-text")

    if mode == "fresh":
        parser.add_argument(
            "--role",
            choices=("flutter", "ai", "hybrid"),
            default="hybrid",
        )
        parser.add_argument("--pages", type=int, required=True)
    else:
        parser.add_argument(
            "--approved-snapshot", type=Path, required=True
        )
        parser.add_argument("--profile", type=Path, default=PROFILE_PATH)
        parser.add_argument("--user-exact-pages", type=int)
        parser.add_argument("--user-max-pages", type=int)
        parser.add_argument("--employer-exact-pages", type=int)
        parser.add_argument("--employer-max-pages", type=int)

    parser.add_argument("--insert-work-id", action="append", default=[])
    parser.add_argument("--experience-anchor")
    parser.add_argument("--project-anchor")
    parser.add_argument("--experience-style-from")
    parser.add_argument("--project-style-from")

    parser.add_argument("--remove-title", action="append", default=[])
    parser.add_argument("--section-start")
    parser.add_argument("--section-end")

    parser.add_argument(
        "--clean-continuation-header", action="store_true"
    )
    parser.add_argument("--identity")
    parser.add_argument("--repeated-heading")
    parser.add_argument("--repeated-links")
    parser.add_argument("--next-section")
    return parser


def _choices(parser, args):
    insertion = None
    insertion_fields = (
        args.experience_anchor,
        args.project_anchor,
        args.experience_style_from,
        args.project_style_from,
    )
    if args.insert_work_id:
        if not all(insertion_fields):
            parser.error(
                "Insertion requires two anchors and two style prototypes."
            )
        insertion = InsertionChoice(
            work_ids=args.insert_work_id,
            experience_anchor=args.experience_anchor,
            project_anchor=args.project_anchor,
            experience_style_from=args.experience_style_from,
            project_style_from=args.project_style_from,
        )
    elif any(insertion_fields):
        parser.error("Insertion anchors/styles require --insert-work-id.")

    removal = None
    if args.remove_title:
        if not args.section_start or not args.section_end:
            parser.error("Removal requires both section boundaries.")
        removal = RemovalChoice(
            titles=args.remove_title,
            section_start=args.section_start,
            section_end=args.section_end,
        )
    elif args.section_start or args.section_end:
        parser.error("Removal boundaries require --remove-title.")

    header_fields = (
        args.identity,
        args.repeated_heading,
        args.repeated_links,
        args.next_section,
    )
    header = None
    if args.clean_continuation_header:
        if not all(header_fields):
            parser.error(
                "Header cleanup needs identity, heading, links and next section."
            )
        header = ContinuationHeaderChoice(
            identity=args.identity,
            repeated_heading=args.repeated_heading,
            repeated_links=args.repeated_links,
            next_section=args.next_section,
        )
    elif any(header_fields):
        parser.error("Header anchors require --clean-continuation-header.")
    return insertion, removal, header


def main(argv: list[str] | None = None) -> None:
    supplied = list(sys.argv[1:] if argv is None else argv)
    mode = (
        supplied.pop(0)
        if supplied and supplied[0] in {"fresh", "snapshot"}
        else "snapshot"
    )
    parser = _parser(mode)
    args = parser.parse_args(supplied)
    insertion, removal, header = _choices(parser, args)

    description = (
        args.jd_file.read_text(encoding="utf-8-sig")
        if args.jd_file else args.jd_text
    )

    if mode == "fresh":
        if not description or not description.strip():
            parser.error("Fresh mode requires --jd-file or --jd-text.")
        if args.pages < 1:
            parser.error("--pages must be a positive number.")
        request = FreshResumeRequest(
            template_path=args.template,
            job_description=description,
            output_root=(
                args.output_root or Path("outputs/fresh_resume_runs")
            ),
            target_role=args.role,
            max_pages=args.pages,
            converter=args.converter,
            insertion=insertion,
            removal=removal,
            continuation_header=header,
            render_images=not args.no_images,
        )
        result = generate_resume_from_jd(request)
    else:
        request = ResumeAssemblyRequest(
            template_path=args.template,
            approved_snapshot_path=args.approved_snapshot,
            profile_path=args.profile,
            output_root=(
                args.output_root or Path("outputs/resume_builds")
            ),
            job_description=description,
            pages=PageRequirements(
                user_exact_pages=args.user_exact_pages,
                user_max_pages=args.user_max_pages,
                employer_exact_pages=args.employer_exact_pages,
                employer_max_pages=args.employer_max_pages,
            ),
            converter=args.converter,
            insertion=insertion,
            removal=removal,
            continuation_header=header,
            render_images=not args.no_images,
        )
        result = assemble_resume(request)

    print(result.model_dump_json(indent=2))
    if result.status == "failed":
        raise SystemExit(1)
    if result.status == "rejected":
        raise SystemExit(2)
    if not result.automated_checks_passed:
        raise SystemExit(3)
    # Exit 0 means automated checks passed; visual review may still be pending.


if __name__ == "__main__":
    main()
