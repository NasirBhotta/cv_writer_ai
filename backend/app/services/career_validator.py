
import re
from typing import Any
from urllib.parse import urlsplit


PROFESSIONAL_CATEGORIES = {
    "employment",
    "experience",
    "professional",
    "internship",
    "job",
    "work",
    "freelance",
    "contract",
}


def _is_professional(work: dict) -> bool:
    category = str(
        work.get("category", "")
    ).lower()

    words = set(
        re.findall(r"[a-z]+", category)
    )

    return bool(
        words & PROFESSIONAL_CATEGORIES
    )


def _company_name(work: dict) -> str:
    organization = work.get("organization")

    if organization:
        return str(organization).strip()

    name = str(work.get("name", ""))

    return re.split(
        r"\s+(?:[—–|-]|â€”|â€“)\s+",
        name,
        maxsplit=1,
    )[0].strip()


def _canonical_url(value: str) -> str | None:
    value = value.strip().strip(
        "<>[](),;."
    )

    if not value:
        return None

    if not value.lower().startswith(
        ("http://", "https://")
    ):
        if "." not in value or " " in value:
            return None

        value = "https://" + value

    parsed = urlsplit(value)

    if not parsed.hostname:
        return None

    host = (
        parsed.hostname.lower()
        .removeprefix("www.")
    )

    path = parsed.path.rstrip("/").lower()

    query = (
        f"?{parsed.query}"
        if parsed.query
        else ""
    )

    return host + path + query


def validate_career_context(
    context: dict[str, Any],
) -> list[str]:
    errors = []

    selected_ids = context.get(
        "selected_fact_ids", []
    )

    work_items = context.get(
        "work_items", []
    )

    if not selected_ids:
        errors.append(
            "No career facts were selected."
        )

    if len(selected_ids) != len(
        set(selected_ids)
    ):
        errors.append(
            "Duplicate selected career fact IDs."
        )

    found_ids = []
    work_ids = []

    for work in work_items:
        work_id = work.get("id")

        if not work_id:
            errors.append(
                "Work item has no ID."
            )
        else:
            work_ids.append(work_id)

        if not work.get("name"):
            errors.append(
                f"Work item {work_id} has no name."
            )

        facts = work.get(
            "selected_facts", []
        )

        if not facts:
            errors.append(
                f"Work item {work_id} "
                "has no selected facts."
            )

        for fact in facts:
            fact_id = fact.get("id")

            description = fact.get(
                "description"
            )

            if not fact_id or not description:
                errors.append(
                    "Invalid selected fact "
                    f"in {work_id}."
                )

            if fact_id:
                found_ids.append(fact_id)

    if len(work_ids) != len(set(work_ids)):
        errors.append(
            "Duplicate work item IDs."
        )

    if len(found_ids) != len(
        set(found_ids)
    ):
        errors.append(
            "A career fact appears more than once."
        )

    if set(found_ids) != set(selected_ids):
        errors.append(
            "Selected fact IDs do not match "
            "career context."
        )

    return errors


def _known_urls(
    context: dict[str, Any],
) -> set[str]:
    candidate = context.get(
        "candidate", {}
    )

    urls = set()

    for field in (
        "github",
        "linkedin",
        "portfolio",
        "website",
    ):
        value = candidate.get(field)

        if isinstance(value, str):
            url = _canonical_url(value)

            if url:
                urls.add(url)

    for work in context.get(
        "work_items", []
    ):
        links = work.get("links") or {}

        if isinstance(links, dict):
            values = links.values()

        elif isinstance(links, list):
            values = links

        else:
            values = []

        for value in values:
            if isinstance(value, str):
                url = _canonical_url(value)

                if url:
                    urls.add(url)

    return urls


def _professional_section(
    draft: str,
) -> str:
    pattern = (
        r"(?im)^(#{1,4})[ \t]+"
        r"(?:professional|work|employment)"
        r"[ \t]+experience[ \t]*$"
    )

    match = re.search(
        pattern, draft
    )

    if not match:
        return ""

    heading_level = len(
        match.group(1)
    )

    remaining = draft[
        match.end():
    ]

    # Company subheadings like ### Crifly
    # should stay inside a ## Experience section.
    next_section_pattern = (
        rf"(?m)^#{{1,{heading_level}}}"
        r"[ \t]+\S"
    )

    next_section = re.search(
        next_section_pattern,
        remaining,
    )

    if next_section:
        return remaining[
            :next_section.start()
        ].strip()

    return remaining.strip()


def _is_internship(
    work: dict,
) -> bool:
    labels = " ".join(
        str(work.get(key) or "")
        for key in (
            "category",
            "role",
            "name",
        )
    ).casefold()

    return "intern" in labels


def _heading_mentions_company(
    heading: str,
    company: str,
) -> bool:
    if not company:
        return False

    pattern = (
        r"(?<!\w)"
        + re.escape(company.casefold())
        + r"(?!\w)"
    )

    return re.search(
        pattern,
        heading.casefold(),
    ) is not None


def _role_matches_heading(
    heading: str,
    work: dict,
) -> bool:
    role = str(
        work.get("role") or ""
    ).strip()

    return bool(
        role
        and role.casefold()
        in heading.casefold()
    )


def _internship_designation_errors(
    section: str,
    professional_items: list[dict],
) -> list[str]:
    """
    Validate individual professional entry headings.

    Multiple roles under the same employer must
    not be confused with one another.
    """
    errors = []

    # Only actual ### entry headings, not bullets.
    headings = re.findall(
        r"(?m)^#{3,6}[ \t]+([^\r\n]+)$",
        section,
    )

    for heading in headings:
        matching = [
            work
            for work in professional_items
            if _heading_mentions_company(
                heading,
                _company_name(work),
            )
        ]

        internships = [
            work
            for work in matching
            if _is_internship(work)
        ]

        if not internships:
            continue

        # Explicitly named internship is valid.
        if re.search(
            r"\bintern(?:ship)?\b",
            heading,
            re.IGNORECASE,
        ):
            continue

        other_roles = [
            work
            for work in matching
            if not _is_internship(work)
        ]

        # Example:
        # Crifly — Part-Time Flutter Developer
        # This is a known non-internship role.
        if any(
            _role_matches_heading(
                heading, work
            )
            for work in other_roles
        ):
            continue

        company = _company_name(
            internships[0]
        ).lower()

        if other_roles:
            errors.append(
                "Ambiguous professional designation "
                f"for {company}: cannot distinguish "
                "internship from another role."
            )

        else:
            errors.append(
                "Internship designation missing "
                f"for {company}."
            )

    return errors


def validate_resume_draft(
    draft: str,
    context: dict[str, Any],
) -> list[str]:
    errors = []

    if not draft or len(
        draft.strip()
    ) < 100:
        return [
            "Resume draft is empty or too short."
        ]

    candidate = context.get(
        "candidate", {}
    )

    name = candidate.get("name")

    if (
        name
        and str(name).lower()
        not in draft.lower()
    ):
        errors.append(
            "Candidate name is missing."
        )

    if not re.search(
        r"(?im)^#{1,4}\s+"
        r"(?:technical|core)\s+skills",
        draft,
    ):
        errors.append(
            "Technical Skills section is missing."
        )

    if not re.search(
        r"(?im)^#{1,4}\s+education\b",
        draft,
    ):
        errors.append(
            "Education section is missing."
        )

    professional_items = [
        work
        for work in context.get(
            "work_items", []
        )
        if _is_professional(work)
    ]

    if professional_items:
        section = _professional_section(
            draft
        )

        if not section:
            errors.append(
                "Professional Experience "
                "section is missing."
            )

        else:
            company_names = {
                _company_name(work).lower()
                for work in professional_items
                if _company_name(work)
            }

            present = sum(
                1
                for company in company_names
                if company in section.lower()
            )

            required = min(
                2,
                len(company_names),
            )

            if present < required:
                errors.append(
                    "Insufficient professional "
                    "experience coverage: "
                    f"{present}/{required} "
                    "relevant employers included."
                )

            # FIX: Check each actual company heading.
            # Do not stop at the employer's first
            # occurrence in the resume.
            errors.extend(
                _internship_designation_errors(
                    section,
                    professional_items,
                )
            )

    # Preserve URL grounding validation.
    allowed_urls = _known_urls(
        context
    )

    draft_urls = re.findall(
        r"https?://[^\s<>)\]]+",
        draft,
        flags=re.IGNORECASE,
    )

    for raw_url in draft_urls:
        url = _canonical_url(
            raw_url
        )

        if (
            url
            and url not in allowed_urls
        ):
            errors.append(
                "URL not found in career evidence: "
                f"{raw_url}"
            )

    return errors
