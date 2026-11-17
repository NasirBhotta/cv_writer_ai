import re

from backend.app.models.template_edit_plan import (
    ParagraphReplacement,
    TemplateEditPlan,
)
from backend.app.models.template_mapping import TemplateMapping
from backend.app.models.template_report import TemplateReport
from backend.app.services.template_structure import validate_template_mapping


BULLET_PREFIXES = ("• ", "- ", "– ")


def _clean_text(text: str) -> bool:
    return (
        bool(text)
        and text == text.strip()
        and not any(char in text for char in ("\n", "\r", "\t", "\x00"))
    )


def validate_edit_plan(
    report: TemplateReport,
    mapping: TemplateMapping,
    plan: TemplateEditPlan,
) -> list[str]:
    errors = validate_template_mapping(report, mapping)

    if plan.template_sha256 != report.sha256:
        errors.append("Edit plan does not match template SHA-256.")

    if mapping.template_sha256 != report.sha256:
        errors.append("Mapping does not match template SHA-256.")

    if not plan.edits:
        errors.append("Edit plan must contain at least one edit.")
        return errors

    blocks = {block.block_id: block for block in report.blocks}
    owners = {
        block_id: region
        for region in mapping.regions
        for block_id in region.content_block_ids
    }
    summary_regions = [
        region for region in mapping.regions if region.section == "summary"
    ]
    seen: set[str] = set()

    for edit in plan.edits:
        if edit.block_id in seen:
            errors.append(f"Duplicate edit target: {edit.block_id}")
        seen.add(edit.block_id)

        if not re.fullmatch(r"body/\d+", edit.block_id):
            errors.append(f"Only top-level body paragraphs are editable: {edit.block_id}")

        if edit.block_id in mapping.protected_block_ids:
            errors.append(f"Cannot edit a protected block: {edit.block_id}")

        block = blocks.get(edit.block_id)
        if block is None or block.text != edit.old_text:
            if edit.section == "summary":
                errors.append("Original summary text does not match inspection report.")
            else:
                errors.append(f"Original bullet text does not match inspection report: {edit.block_id}")

        if not _clean_text(edit.new_text):
            errors.append(f"Edit must be a single clean paragraph: {edit.block_id}")

        region = owners.get(edit.block_id)
        if region is None or region.needs_review or region.section != edit.section:
            errors.append(f"Target is not in a confirmed {edit.section} region: {edit.block_id}")

        if edit.section == "summary":
            if (
                edit.mode != "plain"
                or len(summary_regions) != 1
                or summary_regions[0].needs_review
                or summary_regions[0].content_block_ids != [edit.block_id]
            ):
                errors.append("Summary must have one unambiguous content paragraph.")
        else:
            if edit.mode != "bullet":
                errors.append(f"Experience/project edits must use bullet mode: {edit.block_id}")
            if block is None or not block.text.startswith(BULLET_PREFIXES):
                errors.append(f"Target is not a bullet paragraph: {edit.block_id}")
            if edit.new_text.startswith(BULLET_PREFIXES):
                errors.append(f"New bullet text must omit the bullet marker: {edit.block_id}")

    return errors


def build_resume_edit_plan(
    report: TemplateReport,
    mapping: TemplateMapping,
    *,
    summary: str | None = None,
    bullet_replacements: dict[str, str] | None = None,
) -> TemplateEditPlan:
    blocks = {block.block_id: block for block in report.blocks}
    owners = {
        block_id: region
        for region in mapping.regions
        for block_id in region.content_block_ids
    }
    edits: list[ParagraphReplacement] = []

    if summary is not None:
        summaries = [
            region for region in mapping.regions if region.section == "summary"
        ]
        if (
            len(summaries) != 1
            or summaries[0].needs_review
            or len(summaries[0].content_block_ids) != 1
        ):
            raise ValueError("Cannot safely locate a single summary paragraph.")
        block_id = summaries[0].content_block_ids[0]
        original = blocks.get(block_id)
        if original is None:
            raise ValueError(f"Summary block missing: {block_id}")
        edits.append(
            ParagraphReplacement(
                block_id=block_id,
                section="summary",
                mode="plain",
                old_text=original.text,
                new_text=summary,
            )
        )

    for block_id, replacement in (bullet_replacements or {}).items():
        original = blocks.get(block_id)
        region = owners.get(block_id)
        if original is None or region is None:
            raise ValueError(f"Unknown bullet block: {block_id}")
        if region.section not in {"experience", "projects"}:
            raise ValueError(f"Block is not an experience/project bullet: {block_id}")
        edits.append(
            ParagraphReplacement(
                block_id=block_id,
                section=region.section,
                mode="bullet",
                old_text=original.text,
                new_text=replacement,
            )
        )

    plan = TemplateEditPlan(
        template_sha256=report.sha256,
        edits=edits,
    )
    errors = validate_edit_plan(report, mapping, plan)
    if errors:
        raise ValueError("Unsafe edit plan: " + "; ".join(errors))
    return plan


def build_summary_edit_plan(
    report: TemplateReport,
    mapping: TemplateMapping,
    new_summary: str,
) -> TemplateEditPlan:
    # Compatibility with the previous batch.
    return build_resume_edit_plan(report, mapping, summary=new_summary)


def build_bullet_edit_plan(
    report: TemplateReport,
    mapping: TemplateMapping,
    replacements: dict[str, str],
) -> TemplateEditPlan:
    return build_resume_edit_plan(
        report,
        mapping,
        bullet_replacements=replacements,
    )
