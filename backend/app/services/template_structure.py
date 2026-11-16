
import re

from backend.app.models.template_mapping import (
    TemplateMapping,
)
from backend.app.models.template_report import (
    TemplateBlock,
    TemplateReport,
)


def _normal(text: str) -> str:
    return " ".join(text.casefold().split())


def find_protected_identity_blocks(
    report: TemplateReport,
) -> list[str]:
    """
    Detect likely repeated candidate identity banners.

    These blocks must not be automatically replaced.
    The identification is heuristic and needs review.
    """

    body = [
        block
        for block in report.blocks
        if re.fullmatch(
            r"body/\d+",
            block.block_id,
        )
    ]

    if len(body) < 5:
        return []

    name = _normal(body[0].text)

    # The first paragraph must resemble a name.
    if (
        not 2 <= len(name.split()) <= 6
        or len(name) > 70
        or "@" in name
    ):
        return []

    protected = []

    for index, block in enumerate(
        body[4:],
        start=4,
    ):
        text = _normal(block.text)

        repeats_name = (
            text == name
            or text.startswith(name + " |")
        )

        if not repeats_name:
            continue

        # Protect the repeated candidate banner.
        protected.append(block.block_id)

        # A following short contact/link line may
        # also belong to the repeated header.
        if index + 1 < len(body):
            following = body[index + 1]

            is_contact_line = re.search(
                r"(?i)"
                r"\b(?:linkedin|github|portfolio)\b"
                r"|https?://"
                r"|www\."
                r"|@"
                r"|\b\S+\.com\b",
                following.text,
            )

            if (
                len(following.text) <= 190
                and is_contact_line
            ):
                protected.append(
                    following.block_id
                )

    # Remove duplicate IDs while keeping order.
    return list(dict.fromkeys(protected))


def classify_mixed_block(
    block: TemplateBlock,
) -> str:
    """
    Identify a paragraph inside a mixed section.

    Unknown paragraphs are flagged for review.
    """

    text = block.text.strip().casefold()
    label = text.split(":", 1)[0].strip()

    if re.match(
        r"^(?:languages?|spoken languages?)\b",
        label,
    ):
        return "languages"

    if re.match(
        r"^(?:certifications?|certificates?|licenses?)\b",
        label,
    ):
        return "certifications"

    if re.match(
        r"^(?:education|degrees?|academic|"
        r"coursework|relevant coursework)\b",
        label,
    ):
        return "education"

    # Degree names without explicit field labels.
    if re.match(
        r"^(?:b\.?s\.?|b\.?sc\.?|m\.?s\.?|"
        r"m\.?sc\.?|fsc|hssc|phd|bachelors?|"
        r"masters?|doctorate)\b",
        text,
    ):
        return "education"

    # Common categories for technical skill lines.
    if ":" in text and re.match(
        r"^(?:mobile|frontend|backend|architecture|"
        r"cloud|tools|data|devops|programming|"
        r"frameworks?|tech(?:nical)?|ai|ml|"
        r"databases?|platforms?|engineering|design)\b",
        label,
    ):
        return "skills"

    return "unknown"


def validate_template_mapping(
    report: TemplateReport,
    mapping: TemplateMapping,
) -> list[str]:
    """
    Validate block ownership and protected boundaries.

    Returns errors. No DOCX editing occurs here.
    """

    errors = []

    known = {
        block.block_id
        for block in report.blocks
    }

    protected = mapping.protected_block_ids

    if report.sha256 != mapping.template_sha256:
        errors.append("Template hash mismatch.")

    if len(protected) != len(set(protected)):
        errors.append(
            "Protected block IDs contain duplicates."
        )

    if not set(protected) <= known:
        errors.append(
            "Protected block ID not found in report."
        )

    assigned = set()
    headings = set()

    for region in mapping.regions:
        if region.heading_id not in known:
            errors.append(
                f"Unknown heading: {region.heading_id}"
            )

        if region.heading_id in headings:
            errors.append(
                f"Duplicate heading: {region.heading_id}"
            )

        headings.add(region.heading_id)

        for block_id in region.content_block_ids:
            if block_id not in known:
                errors.append(
                    f"Unknown content block: {block_id}"
                )

            if block_id in assigned:
                errors.append(
                    "Content block belongs to "
                    f"multiple regions: {block_id}"
                )

            assigned.add(block_id)

        if region.section == "mixed":
            ids = [
                item.block_id
                for item in region.sub_blocks
            ]

            if (
                len(ids) != len(set(ids))
                or set(ids)
                != set(region.content_block_ids)
            ):
                errors.append(
                    "Mixed sub-block coverage mismatch: "
                    f"{region.heading_id}"
                )

    if set(protected) & (headings | assigned):
        errors.append(
            "Protected block was assigned to a section."
        )

    if headings & assigned:
        errors.append(
            "Section heading also assigned as content."
        )

    return errors
