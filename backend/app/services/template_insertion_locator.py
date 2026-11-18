
"""Read-only section locator for DOCX insertion.

Multiple possible locations require explicit selection.
This module never edits or approves document content.
"""

import argparse
import json
import re

from pathlib import Path

from docx import Document


_BULLET_PREFIXES = ("• ", "- ", "– ")

_OTHER_SECTION = re.compile(
    r"^(?:PROFILE|SUMMARY|"
    r"EDUCATION(?:,?\s+.*)?|"
    r"TECHNICAL SKILLS|SKILLS(?:\s+.*)?|"
    r"CERTIFICATIONS(?:\s+.*)?|"
    r"LANGUAGES(?:\s+.*)?|"
    r"TECHNICAL CONTENT(?:\s+.*)?)$",
    flags=re.IGNORECASE,
)


def _heading_section(
    text: str,
    style_name: str,
) -> str | None:
    clean = " ".join(text.split())

    # Exclude identity lines, bullets and dates.
    if (
        not clean
        or len(clean) > 100
        or "|" in clean
        or "\t" in text
        or clean.startswith(_BULLET_PREFIXES)
    ):
        return None

    letters = [
        char
        for char in clean
        if char.isalpha()
    ]

    mostly_upper = bool(letters) and (
        sum(
            char.isupper()
            for char in letters
        ) / len(letters) >= 0.78
    )

    heading_style = (
        style_name.casefold().startswith(
            "heading"
        )
    )

    if not (
        mostly_upper or heading_style
    ):
        return None

    if _OTHER_SECTION.fullmatch(clean):
        return "other"

    if re.search(
        r"\b(?:EXPERIENCE|EMPLOYMENT|WORK HISTORY)\b",
        clean,
        re.IGNORECASE,
    ):
        return "experience"

    if re.search(
        r"\b(?:PROJECTS|RESEARCH|AI AGENTS)\b",
        clean,
        re.IGNORECASE,
    ):
        return "project"

    return None


def locate_insertion_positions(
    source_path: str | Path,
) -> dict:
    """
    Locate candidate sections and style examples.

    Auto-selection is allowed only when the target
    section is unique and contains a usable entry
    heading with an immediately following bullet.

    This is NOT content approval.
    """
    path = Path(source_path)

    if not path.is_file():
        raise FileNotFoundError(path)

    document = Document(path)
    paragraphs = document.paragraphs

    headings = []

    # Step 1: Discover section headings.
    for index, paragraph in enumerate(
        paragraphs
    ):
        style_name = (
            paragraph.style.name
            if paragraph.style
            else ""
        )

        kind = _heading_section(
            paragraph.text,
            style_name,
        )

        if kind:
            headings.append(
                (
                    index,
                    kind,
                    paragraph.text.strip(),
                )
            )

    areas = {
        "experience": [],
        "project": [],
    }

    # Step 2: Find heading/bullet prototypes
    # inside each candidate section.
    for position, (
        start,
        kind,
        title,
    ) in enumerate(headings):

        if kind not in areas:
            continue

        end = (
            headings[position + 1][0]
            if position + 1 < len(headings)
            else len(paragraphs)
        )

        examples = []

        for index in range(
            start + 1,
            end - 1,
        ):
            current = paragraphs[index]
            following = paragraphs[index + 1]

            value = current.text.strip()

            style_name = (
                current.style.name
                if current.style
                else ""
            )

            is_section = _heading_section(
                value,
                style_name,
            )

            if (
                value
                and not value.startswith(
                    _BULLET_PREFIXES
                )
                and following.text.startswith(
                    _BULLET_PREFIXES
                )
                and not is_section
            ):
                # Prefix identifies the heading
                # without its date/tab suffix.
                example = value.split(
                    "\t",
                    1,
                )[0].strip()

                examples.append(example)

        areas[kind].append({
            "heading": title,
            "paragraph_index": start,
            "style_examples": examples,
        })

    # Step 3: Only automatically recommend
    # a location when it is unambiguous.
    suggestions = {}

    for kind, candidates in areas.items():
        usable = [
            candidate
            for candidate in candidates
            if candidate["style_examples"]
        ]

        auto = (
            len(candidates) == 1
            and len(usable) == 1
        )

        suggestions[kind] = {
            "candidate_regions": candidates,
            "recommended_anchor": (
                candidates[0]["heading"]
                if auto
                else None
            ),
            "recommended_style_from": (
                usable[0]["style_examples"][0]
                if auto
                else None
            ),
            "requires_review": not auto,
        }

    return {
        "source": str(path),
        "read_only": True,
        "approval_checked": False,
        "locations": suggestions,
        "warnings": [
            (
                f"{kind}: multiple or incomplete "
                "sections; choose anchor/style "
                "explicitly"
            )
            for kind, item in suggestions.items()
            if item["requires_review"]
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Find read-only DOCX insertion locations"
        )
    )

    parser.add_argument(
        "--source",
        required=True,
    )

    args = parser.parse_args()

    result = locate_insertion_positions(
        args.source
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
