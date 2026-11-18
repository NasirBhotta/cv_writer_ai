
"""DOCX -> PDF pagination QA CLI; never changes source document."""

import argparse
import json
import tempfile
from pathlib import Path

from backend.app.models.page_layout_policy import (
    PageRequirements,
)
from backend.app.services.resume_layout_qa import (
    audit_resume_layout,
    export_docx_to_pdf,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Measure rendered CV pages "
            "and create QA page images"
        )
    )

    parser.add_argument(
        "--docx",
        required=True,
    )

    parser.add_argument(
        "--pdf",
        help="Use an existing exported PDF",
    )

    parser.add_argument(
        "--template",
        help="Original user DOCX for page preference",
    )

    parser.add_argument(
        "--template-pdf",
        help="Already-rendered original template PDF",
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
        "--render-dir",
        default="outputs/layout_qa_pages",
    )

    parser.add_argument(
        "--report",
        default="outputs/layout_qa_report.json",
    )

    parser.add_argument(
        "--export-pdf",
        default="outputs/layout_preview.pdf",
    )

    args = parser.parse_args()

    if args.template and args.template_pdf:
        parser.error(
            "Choose --template or --template-pdf, "
            "not both."
        )

    requirements = PageRequirements(
        user_exact_pages=args.user_exact_pages,
        user_max_pages=args.user_max_pages,
        employer_exact_pages=args.employer_exact_pages,
        employer_max_pages=args.employer_max_pages,
    )

    with tempfile.TemporaryDirectory(
        prefix="cv-original-layout-"
    ) as temp:

        template_pdf = args.template_pdf

        if args.template:
            template_pdf = str(
                Path(temp) / "original.pdf"
            )

            export_docx_to_pdf(
                args.template,
                template_pdf,
                engine=args.converter,
            )

        pdf = args.pdf

        if pdf is None:
            pdf = str(
                export_docx_to_pdf(
                    args.docx,
                    args.export_pdf,
                    engine=args.converter,
                )
            )

        report = audit_resume_layout(
            source_docx=args.docx,
            pdf_path=pdf,
            template_pdf_path=template_pdf,
            requirements=requirements,
            render_dir=args.render_dir,
            pdf_generated_from_source_this_run=(
                args.pdf is None
            ),
        )

        if args.template:
            report.template_pdf_path = None

            report.warnings.append(
                "Original template was measured "
                "through a temporary PDF; the "
                "temporary export has been deleted."
            )

    output = Path(args.report)

    if output.exists():
        raise FileExistsError(
            "Refusing to overwrite an existing "
            f"report: {output}"
        )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "actual_pages": report.actual_pages,
                "template_pages": report.template_pages,
                "mode": report.decision.mode,
                "automated_checks_passed": (
                    report.automated_checks_passed
                ),
                "visual_review_pending": (
                    report.visual_review_pending
                ),
                "errors": report.errors,
                "warnings": report.warnings,
                "page_images": report.page_images,
                "report": str(output),
            },
            indent=2,
        )
    )

    if not report.automated_checks_passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
