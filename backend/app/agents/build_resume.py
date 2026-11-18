
"""One-command snapshot -> template DOCX/PDF review package.

Not yet a fresh JD -> graph runner or multi-user profile service.
"""

import argparse
from pathlib import Path

from backend.app.models.page_layout_policy import (
    PageRequirements,
)

from backend.app.models.resume_pipeline_result import (
    InsertionChoice,
    RemovalChoice,
    ResumeAssemblyRequest,
)

from backend.app.services.profile_store import (
    PROFILE_PATH,
)

from backend.app.services.resume_pipeline_orchestrator import (
    assemble_resume,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    parser.add_argument(
        "--template",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--approved-snapshot",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--profile",
        type=Path,
        default=PROFILE_PATH,
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("outputs/resume_builds"),
    )

    jd = parser.add_mutually_exclusive_group()

    jd.add_argument(
        "--jd-file",
        type=Path,
    )

    jd.add_argument(
        "--jd-text",
    )

    parser.add_argument(
        "--user-exact-pages",
        type=int,
    )

    parser.add_argument(
        "--user-max-pages",
        type=int,
    )

    parser.add_argument(
        "--employer-exact-pages",
        type=int,
    )

    parser.add_argument(
        "--employer-max-pages",
        type=int,
    )

    parser.add_argument(
        "--converter",
        choices=(
            "auto",
            "word",
            "libreoffice",
        ),
        default="auto",
    )

    parser.add_argument(
        "--no-images",
        action="store_true",
    )

    parser.add_argument(
        "--insert-work-id",
        action="append",
        default=[],
    )

    parser.add_argument(
        "--experience-anchor",
    )

    parser.add_argument(
        "--project-anchor",
    )

    parser.add_argument(
        "--experience-style-from",
    )

    parser.add_argument(
        "--project-style-from",
    )

    parser.add_argument(
        "--remove-title",
        action="append",
        default=[],
    )

    parser.add_argument(
        "--section-start",
    )

    parser.add_argument(
        "--section-end",
    )

    args = parser.parse_args()

    insertion = None

    fields = (
        args.experience_anchor,
        args.project_anchor,
        args.experience_style_from,
        args.project_style_from,
    )

    if args.insert_work_id:
        if not all(fields):
            parser.error(
                "Insertion requires both anchors "
                "and both style prototypes."
            )

        insertion = InsertionChoice(
            work_ids=args.insert_work_id,
            experience_anchor=(
                args.experience_anchor
            ),
            project_anchor=(
                args.project_anchor
            ),
            experience_style_from=(
                args.experience_style_from
            ),
            project_style_from=(
                args.project_style_from
            ),
        )

    elif any(fields):
        parser.error(
            "Insertion anchors/styles require "
            "--insert-work-id."
        )

    removal = None

    if args.remove_title:
        if (
            not args.section_start
            or not args.section_end
        ):
            parser.error(
                "Removal requires --section-start "
                "and --section-end."
            )

        removal = RemovalChoice(
            titles=args.remove_title,
            section_start=(
                args.section_start
            ),
            section_end=(
                args.section_end
            ),
        )

    elif (
        args.section_start
        or args.section_end
    ):
        parser.error(
            "Removal boundaries require "
            "--remove-title."
        )

    description = (
        args.jd_file.read_text(
            encoding="utf-8-sig"
        )
        if args.jd_file
        else args.jd_text
    )

    request = ResumeAssemblyRequest(
        template_path=args.template,
        approved_snapshot_path=(
            args.approved_snapshot
        ),
        profile_path=args.profile,
        output_root=args.output_root,
        job_description=description,
        pages=PageRequirements(
            user_exact_pages=(
                args.user_exact_pages
            ),
            user_max_pages=(
                args.user_max_pages
            ),
            employer_exact_pages=(
                args.employer_exact_pages
            ),
            employer_max_pages=(
                args.employer_max_pages
            ),
        ),
        converter=args.converter,
        insertion=insertion,
        removal=removal,
        render_images=not args.no_images,
    )

    result = assemble_resume(
        request
    )

    print(
        result.model_dump_json(
            indent=2
        )
    )

    if result.status == "failed":
        raise SystemExit(1)

    if not result.automated_checks_passed:
        raise SystemExit(2)

    # Exit 0 means automated checks passed,
    # NOT that human visual QA is complete.


if __name__ == "__main__":
    main()
