
import argparse
import hashlib
import json

from pathlib import Path

from backend.app.models.resume_document import ResumeDocument
from backend.app.services.profile_store import (
    load_profile,
    PROFILE_PATH,
)
from backend.app.services.career_context import (
    build_career_context,
)
from backend.app.services.docx_exporter import (
    export_resume_docx,
)


def main():
    parser = argparse.ArgumentParser(
        description="Export a saved resume to DOCX"
    )

    parser.add_argument(
        "--template",
        required=True,
        help="Path to the DOCX template",
    )

    parser.add_argument(
        "--output",
        default="outputs/resume.docx",
        help="Destination DOCX path",
    )

    parser.add_argument(
        "--snapshot",
        default=(
            ".cache/resume_pipeline/"
            "last_resume_run.json"
        ),
    )

    parser.add_argument(
        "--allow-unreviewed",
        action="store_true",
        help="Allow exporting a resume that failed evaluation",
    )

    args = parser.parse_args()

    snapshot = json.loads(
        Path(args.snapshot).read_text(
            encoding="utf-8"
        )
    )

    if (
        not snapshot.get("quality_passed", False)
        and not args.allow_unreviewed
    ):
        raise SystemExit(
            "Resume did not pass evaluation. "
            "Use --allow-unreviewed for a draft export."
        )

    current_hash = hashlib.sha256(
        PROFILE_PATH.read_bytes()
    ).hexdigest()

    if snapshot.get("profile_sha256") != current_hash:
        raise SystemExit(
            "Master Profile changed after generation. "
            "Generate a new resume before exporting."
        )

    profile = load_profile()

    context = build_career_context(
        profile=profile,
        selected_fact_ids=snapshot[
            "selected_fact_ids"
        ],
    )

    document = ResumeDocument.model_validate(
        snapshot["resume_document"]
    )

    output = export_resume_docx(
        resume=document,
        context=context,
        template_path=args.template,
        output_path=args.output,
    )

    print("DOCX exported:", output)


if __name__ == "__main__":
    main()
