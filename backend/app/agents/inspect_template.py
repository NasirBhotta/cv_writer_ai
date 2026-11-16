
import argparse
from pathlib import Path

from backend.app.services.template_mapper import map_template
from backend.app.services.template_inspector import (
    inspect_template,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect a user-uploaded DOCX CV template"
    )

    parser.add_argument(
        "--template",
        required=True,
        help="Original DOCX template path",
    )

    parser.add_argument(
        "--output",
        help="Optional report JSON path",
    )

    args = parser.parse_args()

    # Step 1: Inspect the actual DOCX template
    report = inspect_template(args.template)

    # Step 2: Detect sections and content boundaries
    mapping = map_template(report)

    # Step 3: Determine inspection report location
    output = (
        Path(args.output)
        if args.output
        else (
            Path(".cache/template_inspections")
            / (
                f"{Path(args.template).stem}_"
                f"{report.sha256[:8]}.json"
            )
        )
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # Step 4: Save inspection report
    output.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )

    print(f"\nTemplate: {report.filename}")
    print(f"Paragraph blocks: {len(report.blocks)}")

    print(
        "Section hints:",
        [
            (hint.section, hint.block_id)
            for hint in report.section_hints
        ],
    )

    for warning in report.warnings:
        print(f"WARNING: {warning}")

    print(f"Saved inspection report: {output}")

    # Step 5: Save section mapping in a separate JSON
    mapping_path = output.with_name(
        f"{output.stem}_mapping.json"
    )

    mapping_path.write_text(
        mapping.model_dump_json(indent=2),
        encoding="utf-8",
    )

    # Step 6: Display identified sections
    print("\n--- DETECTED SECTIONS ---")

    for region in mapping.regions:
        status = (
            "REVIEW"
            if region.needs_review
            else "MAPPED"
        )

        print(
            f"[{status}] "
            f"{region.heading_id} "
            f"{region.section}: "
            f"{region.heading_text}"
        )

        print(
            "  Content blocks:",
            len(region.content_block_ids),
        )

    # Step 7: Display mapping warnings
    for warning in mapping.warnings:
        print(f"WARNING: {warning}")

    print(f"\nSaved mapping report: {mapping_path}")


if __name__ == "__main__":
    main()
