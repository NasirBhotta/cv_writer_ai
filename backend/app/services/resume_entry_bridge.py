
from backend.app.models.profile import MasterProfile
from backend.app.models.resume_document import ResumeDocument

from backend.app.models.template_entry_map import (
    DocumentBridgeResult,
    TemplateEntryMap,
)
from backend.app.models.template_mapping import (
    TemplateMapping,
)
from backend.app.models.template_report import (
    TemplateReport,
)

from backend.app.services.template_edit_planner import (
    build_resume_edit_plan,
)


def build_document_edit_plan(
    report: TemplateReport,
    mapping: TemplateMapping,
    entry_map: TemplateEntryMap,
    profile: MasterProfile,
    document: ResumeDocument | dict,
    *,
    allowed_fact_ids: set[str] | None = None,
    allow_partial: bool = False,
) -> DocumentBridgeResult:
    """
    Convert generated resume entries into safe DOCX
    paragraph replacements.

    ResumeDocument section labels:
        "experience", "project"

    Template section labels:
        "experience", "projects"

    This produces a preview edit plan only.
    It does not guarantee a complete tailored CV.
    """

    # Step 1: Verify all mapping data belongs
    # to the same original DOCX.
    if entry_map.template_sha256 != report.sha256:
        raise ValueError(
            "Entry mapping is for a different "
            "template version."
        )

    if mapping.template_sha256 != report.sha256:
        raise ValueError(
            "Section mapping is for a different "
            "template version."
        )

    # Step 2: Validate the structured resume.
    resume = ResumeDocument.model_validate(
        document
    )

    # Step 3: Index original career work records.
    works = {
        item.id: item
        for item in profile.work_items
    }

    # Step 4: Group template slots by work_id.
    slots: dict[str, list] = {}

    for slot in entry_map.slots:
        if slot.work_id is not None:
            slots.setdefault(
                slot.work_id,
                [],
            ).append(slot)

    replacements: dict[str, str] = {}
    skipped: list[str] = []
    visited: set[str] = set()

    # Step 5: Process every AI-generated entry.
    for entry in resume.entries:

        # Prevent duplicate ResumeDocument entries.
        if entry.work_id in visited:
            skipped.append(
                f"{entry.work_id}: repeated "
                "ResumeDocument entry"
            )
            continue

        visited.add(entry.work_id)

        work = works.get(entry.work_id)

        if work is None:
            skipped.append(
                f"{entry.work_id}: unknown "
                "profile work_id"
            )
            continue

        # FIX: ResumeDocument and TemplateMapping
        # use different names for project sections.
        if work.category in {"job", "internship"}:
            resume_section = "experience"
            template_section = "experience"

        elif work.category == "project":
            resume_section = "project"
            template_section = "projects"

        else:
            skipped.append(
                f"{entry.work_id}: unsupported "
                "work category"
            )
            continue

        # Check against ResumeDocument terminology.
        if entry.section != resume_section:
            skipped.append(
                f"{entry.work_id}: profile "
                "section mismatch"
            )
            continue

        # Step 6: Validate the fact IDs.
        # Every fact must belong to this work item.
        facts = {
            fact.id
            for fact in work.facts
        }

        invalid_facts = [
            bullet.fact_id
            for bullet in entry.bullets
            if (
                bullet.fact_id not in facts
                or (
                    allowed_fact_ids is not None
                    and bullet.fact_id
                    not in allowed_fact_ids
                )
            )
        ]

        if invalid_facts:
            skipped.append(
                f"{entry.work_id}: unsupported "
                f"fact_id(s) {invalid_facts}"
            )
            continue

        # Step 7: Find the original DOCX entry.
        matches = slots.get(entry.work_id, [])

        if (
            len(matches) != 1
            or matches[0].needs_review
        ):
            skipped.append(
                f"{entry.work_id}: no unique "
                "approved template entry"
            )
            continue

        slot = matches[0]

        # FIX: Compare against TemplateMapping
        # terminology, not ResumeDocument terminology.
        if slot.section != template_section:
            skipped.append(
                f"{entry.work_id}: template "
                "section mismatch"
            )
            continue

        # This version supports only existing slots.
        # Dynamic adding/removing comes later.
        if (
            len(slot.bullet_block_ids)
            != len(entry.bullets)
        ):
            skipped.append(
                f"{entry.work_id}: bullet count "
                "differs "
                f"(template={len(slot.bullet_block_ids)}, "
                f"generated={len(entry.bullets)})"
            )
            continue

        if not entry.bullets:
            skipped.append(
                f"{entry.work_id}: no bullet content"
            )
            continue

        # Step 8: Match each AI-generated bullet
        # to its original DOCX paragraph.
        for block_id, bullet in zip(
            slot.bullet_block_ids,
            entry.bullets,
            strict=True,
        ):
            replacements[block_id] = bullet.text

    # Step 9: Reject incomplete mapping by default.
    if skipped and not allow_partial:
        raise ValueError(
            "Resume-to-template alignment incomplete: "
            + "; ".join(skipped)
        )

    # Step 10: Reuse our existing edit planner.
    plan = (
        build_resume_edit_plan(
            report,
            mapping,
            bullet_replacements=replacements,
        )
        if replacements
        else None
    )

    return DocumentBridgeResult(
        plan=plan,
        skipped=skipped,
        preview_only=True,
    )
