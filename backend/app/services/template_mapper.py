
import re

from backend.app.models.template_report import (
    TemplateBlock,
    TemplateReport,
)
from backend.app.models.template_mapping import (
    MappedSubBlock,
    TemplateMapping,
    TemplateRegion,
)
from backend.app.services.template_structure import (
    classify_mixed_block,
    find_protected_identity_blocks,
    validate_template_mapping,
)


SECTION_TERMS = {
    "summary": (
        "profile", "summary", "about me", "objective"
    ),
    "experience": (
        "experience", "employment", "work history",
        "internship", "career history"
    ),
    "projects": (
        "project", "projects", "research",
        "portfolio projects"
    ),
    "skills": (
        "skills", "technical expertise",
        "tech stack", "competencies"
    ),
    "education": (
        "education", "academic background",
        "qualification", "qualifications"
    ),
    "languages": (
        "language", "languages"
    ),
    "certifications": (
        "certification", "certifications",
        "certificates"
    ),
    "technical_content": (
        "technical content", "video",
        "publications", "technical writing"
    ),
    "featured_work": (
        "featured", "work sample", "case study"
    ),
}


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _section_labels(text: str) -> list[str]:
    normalized = _normalize(text)
    labels = []

    for section, terms in SECTION_TERMS.items():
        for term in terms:
            pattern = (
                r"(?<!\w)"
                + re.escape(term)
                + r"(?!\w)"
            )

            if re.search(pattern, normalized):
                labels.append(section)
                break

    return labels


def _looks_like_heading(
    block: TemplateBlock,
    position: int,
    first_line: str,
) -> bool:
    text = block.text.strip()

    if not text or len(text) > 100:
        return False

    if "\t" in text or "@" in text:
        return False

    if text.startswith(("•", "-", "–")):
        return False

    if (
        first_line
        and _normalize(first_line) in _normalize(text)
        and (
            position == 0
            or len(text) > len(first_line)
        )
    ):
        return False

    if position < 4 and text.count("|") >= 2:
        return False

    if block.style_name.casefold().startswith(
        "heading"
    ):
        return True

    letters = [
        char
        for char in text
        if char.isalpha()
    ]

    if not letters:
        return False

    uppercase_ratio = (
        sum(char.isupper() for char in letters)
        / len(letters)
    )

    return (
        uppercase_ratio >= 0.85
        and len(text.split()) <= 14
    )


def map_template(
    report: TemplateReport,
) -> TemplateMapping:

    body_blocks = [
        block
        for block in report.blocks
        if re.fullmatch(
            r"body/\d+",
            block.block_id,
        )
    ]

    first_line = (
        body_blocks[0].text
        if body_blocks
        else ""
    )

    # NEW: Protect likely repeated identity blocks.
    protected_ids = find_protected_identity_blocks(
        report
    )

    protected = set(protected_ids)

    headings = []

    for position, block in enumerate(body_blocks):
        if block.block_id in protected:
            continue

        if _looks_like_heading(
            block, position, first_line
        ):
            headings.append(
                (
                    position,
                    block,
                    _section_labels(block.text),
                )
            )

    regions = []

    for index, (start, heading, labels) in enumerate(
        headings
    ):
        end = (
            headings[index + 1][0]
            if index + 1 < len(headings)
            else len(body_blocks)
        )

        # NEW: Never assign protected blocks as content.
        content_blocks = [
            block
            for block in body_blocks[start + 1:end]
            if block.block_id not in protected
        ]

        if len(labels) == 1:
            section = labels[0]
        elif len(labels) > 1:
            section = "mixed"
        else:
            section = "unknown"

        normalized = _normalize(heading.text)

        ambiguous_research = (
            section == "projects"
            and "research" in normalized
            and "project" not in normalized
        )

        needs_review = (
            section in {"mixed", "unknown"}
            or ambiguous_research
        )

        # NEW: Classify paragraphs inside mixed sections.
        sub_blocks = []

        if section == "mixed":
            for block in content_blocks:
                label = classify_mixed_block(block)

                sub_blocks.append(
                    MappedSubBlock(
                        block_id=block.block_id,
                        section=label,
                        needs_review=(
                            label == "unknown"
                        ),
                    )
                )

        regions.append(
            TemplateRegion(
                section=section,
                heading_id=heading.block_id,
                heading_text=heading.text,
                possible_sections=labels,
                content_block_ids=[
                    block.block_id
                    for block in content_blocks
                ],
                sub_blocks=sub_blocks,
                needs_review=needs_review,
            )
        )

    warnings = list(report.warnings)

    if protected_ids:
        warnings.append(
            "Possible repeated identity/header blocks "
            "protected from replacement: "
            + ", ".join(protected_ids)
            + ". Verify visually."
        )

    if not regions:
        warnings.append(
            "No section boundaries detected. "
            "Manual or AI-assisted mapping is needed."
        )

    if any(
        region.needs_review
        for region in regions
    ):
        warnings.append(
            "Some section mappings require review."
        )

    if any(
        block.block_id.startswith("body/")
        and "/r" in block.block_id
        for block in report.blocks
    ):
        warnings.append(
            "Table-cell content is not assigned to "
            "top-level section boundaries yet."
        )

    mapping = TemplateMapping(
        template_sha256=report.sha256,
        regions=regions,
        protected_block_ids=protected_ids,
        warnings=warnings,
    )

    # NEW: Reject inconsistent block ownership.
    errors = validate_template_mapping(
        report,
        mapping,
    )

    if errors:
        raise ValueError(
            "Unsafe template mapping: "
            + "; ".join(errors)
        )

    return mapping
