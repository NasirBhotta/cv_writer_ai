
"""CLI for selective DOCX entry removal."""

import argparse
import json

from backend.app.services.safe_entry_removal import (
    apply_entry_removal,
    plan_entry_removal,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Review or selectively remove "
            "obsolete DOCX entries"
        )
    )

    parser.add_argument(
        "--source",
        required=True,
    )

    parser.add_argument(
        "--snapshot",
        required=True,
    )

    parser.add_argument(
        "--section-start",
        required=True,
    )

    parser.add_argument(
        "--section-end",
        required=True,
    )

    parser.add_argument(
        "--remove",
        nargs="+",
        required=True,
        help=(
            "Exact headings of entries to remove. "
            "Quote titles containing spaces."
        ),
    )

    parser.add_argument(
        "--output",
        default=(
            "outputs/"
            "selective_removal_preview.docx"
        ),
    )

    parser.add_argument(
        "--apply",
        action="store_true",
    )

    args = parser.parse_args()

    if args.apply:
        result = apply_entry_removal(
            source_path=args.source,
            snapshot_path=args.snapshot,
            output_path=args.output,
            section_start=args.section_start,
            section_end=args.section_end,
            remove_titles=args.remove,
        )

    else:
        plan = plan_entry_removal(
            source_path=args.source,
            snapshot_path=args.snapshot,
            section_start=args.section_start,
            section_end=args.section_end,
            remove_titles=args.remove,
        )

        result = plan.model_dump()
        result["can_apply"] = plan.can_apply
        result["dry_run"] = True

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
