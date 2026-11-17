
import re
from difflib import SequenceMatcher

from backend.app.models.template_entry_map import (
    TemplateEntryMap,
    TemplateEntrySlot,
)
from backend.app.models.template_mapping import TemplateMapping
from backend.app.models.template_report import TemplateReport
from backend.app.models.profile import WorkItem


BULLET_MARKERS = ("• ", "- ", "– ")


def _normal(text: str) -> str:
    return " ".join(
        re.findall(r"[a-z0-9]+", text.casefold())
    )


def _title(text: str) -> str:
    # Word often separates title and dates with tabs.
    return text.split("\t", 1)[0].strip()


def _aliases(name: str) -> set[str]:
    parts = re.split(
        r"\s+[—–]\s+|\s+/\s+",
        name,
        maxsplit=1,
    )

    result = {
        _normal(name),
        _normal(parts[0]),
    }

    if (
        len(parts) > 1
        and len(_normal(parts[1])) >= 12
    ):
        result.add(_normal(parts[1]))

    return {
        alias
        for alias in result
        if alias
    }


def _match_experience(
    title: str,
    items: list[WorkItem],
) -> tuple[str | None, bool]:

    normalized = _normal(title)
    candidates: list[tuple[float, str]] = []

    for item in items:
        if (
            item.category not in {"job", "internship"}
            or not item.organization
        ):
            continue

        org = _normal(item.organization)

        pattern = (
            r"(?<!\w)"
            + re.escape(org)
            + r"(?!\w)"
        )

        if not re.search(pattern, normalized):
            continue

        role_text = _normal(
            re.sub(
                r"(?i)" + re.escape(item.organization),
                " ",
                title,
            )
        )

        role = _normal(item.role or "")

        if not role:
            continue

        # Do not match an internship with a
        # non-internship role at the same company.
        if (
            "intern" in role_text.split()
        ) != (
            "intern" in role.split()
        ):
            continue

        score = SequenceMatcher(
            None,
            role_text,
            role,
        ).ratio()

        if score >= 0.68:
            candidates.append(
                (score, item.id)
            )

    candidates.sort(reverse=True)

    if not candidates:
        return None, False

    # Close competing matches require review.
    if (
        len(candidates) > 1
        and candidates[0][0] - candidates[1][0] < 0.12
    ):
        return None, True

    return candidates[0][1], False


def _match_project(
    title: str,
    items: list[WorkItem],
) -> tuple[str | None, bool]:

    normalized = _normal(title)

    prefix = _normal(
        re.split(
            r"\s+[—–]\s+",
            title,
            maxsplit=1,
        )[0]
    )

    projects = [
        item
        for item in items
        if item.category == "project"
    ]

    # First: exact normalized name or alias.
    exact = [
        item.id
        for item in projects
        if normalized in _aliases(item.name)
    ]

    if len(exact) == 1:
        return exact[0], False

    if len(exact) > 1:
        return None, True

    # Second: unique project-name prefix.
    alias = [
        item.id
        for item in projects
        if (
            len(prefix) >= 6
            and prefix in _aliases(item.name)
        )
    ]

    if len(alias) == 1:
        return alias[0], False

    if len(alias) > 1:
        return None, True

    # Third: only very close fuzzy matches.
    scores = sorted(
        (
            (
                SequenceMatcher(
                    None,
                    normalized,
                    _normal(item.name),
                ).ratio(),
                item.id,
            )
            for item in projects
        ),
        reverse=True,
    )

    if (
        not scores
        or scores[0][0] < 0.88
    ):
        return None, False

    if (
        len(scores) > 1
        and scores[0][0] - scores[1][0] < 0.15
    ):
        return None, True

    return scores[0][1], False


def map_template_entries(
    report: TemplateReport,
    mapping: TemplateMapping,
    work_items: list[WorkItem],
) -> TemplateEntryMap:

    if report.sha256 != mapping.template_sha256:
        raise ValueError(
            "Template report and section mapping "
            "hashes differ."
        )

    blocks = {
        block.block_id: block
        for block in report.blocks
    }

    slots: list[TemplateEntrySlot] = []
    warnings: list[str] = []

    for region in mapping.regions:
        if region.section not in {
            "experience", "projects"
        }:
            continue

        pending_id: str | None = None
        pending_bullets: list[str] = []

        def finish() -> None:
            if (
                pending_id is None
                or not pending_bullets
            ):
                return

            heading = blocks[pending_id]
            title = _title(heading.text)

            if region.section == "experience":
                work_id, ambiguous = _match_experience(
                    title, work_items
                )
            else:
                work_id, ambiguous = _match_project(
                    title, work_items
                )

            review = (
                region.needs_review
                or ambiguous
                or work_id is None
            )

            slots.append(
                TemplateEntrySlot(
                    section=region.section,
                    heading_block_id=pending_id,
                    heading_text=heading.text,
                    bullet_block_ids=list(
                        pending_bullets
                    ),
                    work_id=work_id,
                    needs_review=review,
                )
            )

            if review:
                warnings.append(
                    f"Review entry {pending_id}: {title}"
                )

        for block_id in region.content_block_ids:
            block = blocks.get(block_id)

            if block is None:
                raise ValueError(
                    "Missing block in inspection report: "
                    f"{block_id}"
                )

            if block.text.startswith(BULLET_MARKERS):
                if pending_id is not None:
                    pending_bullets.append(block_id)

            else:
                finish()
                pending_id = block_id
                pending_bullets = []

        finish()

    # One work item must not claim two slots.
    by_work: dict[str, list[TemplateEntrySlot]] = {}

    for slot in slots:
        if slot.work_id:
            by_work.setdefault(
                slot.work_id, []
            ).append(slot)

    for work_id, matches in by_work.items():
        if len(matches) > 1:
            warnings.append(
                "Repeated work_id needs review: "
                f"{work_id}"
            )

            for slot in matches:
                slot.needs_review = True

    return TemplateEntryMap(
        template_sha256=report.sha256,
        slots=slots,
        warnings=warnings,
    )
