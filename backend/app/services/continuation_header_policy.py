
"""Safely remove an explicitly approved repeated page header."""

import argparse
import hashlib
import json
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn


def _sha256(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def _urls(doc, paragraph) -> set[str]:
    """Read actual hyperlink destinations, not just displayed labels."""
    result = set()

    for link in paragraph._p.xpath(
        ".//w:hyperlink"
    ):
        rid = link.get(qn("r:id"))

        if not rid or rid not in doc.part.rels:
            raise ValueError(
                "Unresolved hyperlink; manual review required."
            )

        url = str(
            doc.part.rels[rid].target_ref
        ).strip().rstrip("/").casefold()

        result.add(url)

    return result


def remove_redundant_continuation_header(
    *,
    source_path: str | Path,
    output_path: str | Path,
    identity: str,
    repeated_heading: str,
    repeated_links: str,
    next_section: str,
    dry_run: bool = True,
) -> dict:
    """Remove only a verified, user-approved duplicate header block."""

    source = Path(source_path).resolve()
    output = Path(output_path).resolve()

    if source == output:
        raise ValueError(
            "Output must differ from source."
        )

    if (
        not source.is_file()
        or source.suffix.lower() != ".docx"
    ):
        raise ValueError(
            "Source must be an existing DOCX."
        )

    if output.suffix.lower() != ".docx":
        raise ValueError(
            "Output must be a DOCX."
        )

    if not all(
        text and text.strip()
        for text in (
            identity,
            repeated_heading,
            repeated_links,
            next_section,
        )
    ):
        raise ValueError(
            "All approved header anchors are required."
        )

    if not dry_run and output.exists():
        raise FileExistsError(output)

    original_hash = _sha256(source)

    doc = Document(source)
    paragraphs = doc.paragraphs

    identity_matches = [
        i
        for i, p in enumerate(paragraphs)
        if p.text.strip() == identity.strip()
    ]

    if len(identity_matches) != 1:
        raise ValueError(
            "Cannot uniquely verify the first-page identity."
        )

    matches = []

    for i in range(len(paragraphs) - 3):
        page_break = paragraphs[i]

        valid_break = (
            not page_break.text.strip()
            and len(
                page_break._p.xpath(
                    './/w:br[@w:type="page"]'
                )
            ) == 1
        )

        if (
            valid_break
            and paragraphs[i + 1].text.strip()
            == repeated_heading.strip()
            and paragraphs[i + 2].text.strip()
            == repeated_links.strip()
            and paragraphs[i + 3].text.strip()
            == next_section.strip()
        ):
            matches.append(i)

    if len(matches) != 1:
        raise ValueError(
            "No unique approved continuation-header block."
        )

    break_index = matches[0]

    if identity_matches[0] >= break_index:
        raise ValueError(
            "Identity does not precede continuation header."
        )

    heading = repeated_heading.strip()
    person = identity.strip()

    if not (
        heading.casefold().startswith(
            person.casefold()
        )
        and heading[len(person):]
        .lstrip()
        .startswith("|")
    ):
        raise ValueError(
            "Repeated heading is not linked to verified identity."
        )

    # Only first manual continuation boundary is supported.
    if any(
        p._p.xpath(
            './/w:br[@w:type="page"]'
        )
        for p in paragraphs[:break_index]
    ):
        raise ValueError(
            "Not the first manual continuation boundary."
        )

    repeated_paragraph = paragraphs[
        break_index + 2
    ]

    repeated_urls = _urls(
        doc,
        repeated_paragraph,
    )

    if not repeated_urls:
        raise ValueError(
            "No verifiable repeated hyperlinks."
        )

    # Guard against deleting unique, unlinked information.
    plain_nodes = repeated_paragraph._p.xpath(
        "./w:r/w:t"
    )

    unlinked_text = "".join(
        node.text or ""
        for node in plain_nodes
    )

    if unlinked_text.strip(" |\t\r\n"):
        raise ValueError(
            "Unique unlinked text found; manual review required."
        )

    first_page_urls = set()

    for p in paragraphs[:break_index]:
        first_page_urls.update(
            _urls(doc, p)
        )

    if not repeated_urls.issubset(
        first_page_urls
    ):
        raise ValueError(
            "A repeated URL is not present on first page."
        )

    report = {
        "dry_run": dry_run,
        "source": str(source),
        "output": (
            None if dry_run else str(output)
        ),
        "planned_removed_paragraphs": 2,
        "removed_paragraphs": (
            0 if dry_run else 2
        ),
        "preserved_page_break": True,
        "duplicate_urls_verified": len(
            repeated_urls
        ),
        "source_unchanged": True,
    }

    if dry_run:
        return report

    before = [
        p.text
        for p in paragraphs
    ]

    expected = [
        text
        for index, text in enumerate(before)
        if index not in {
            break_index + 1,
            break_index + 2,
        }
    ]

    # Remove in reverse order so indexes remain stable.
    for index in (
        break_index + 2,
        break_index + 1,
    ):
        element = paragraphs[index]._element

        element.getparent().remove(
            element
        )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    created = False

    try:
        with output.open("xb") as target:
            created = True
            doc.save(target)

        reopened = Document(output)

        if [
            p.text
            for p in reopened.paragraphs
        ] != expected:
            raise RuntimeError(
                "Unexpected changes to preserved paragraphs."
            )

        if not reopened.paragraphs[
            break_index
        ]._p.xpath(
            './/w:br[@w:type="page"]'
        ):
            raise RuntimeError(
                "Original page break was lost."
            )

        if _sha256(source) != original_hash:
            raise RuntimeError(
                "Source DOCX changed."
            )

    except Exception:
        if created:
            output.unlink(
                missing_ok=True
            )
        raise

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__
    )

    for name in (
        "source",
        "output",
        "identity",
        "repeated-heading",
        "repeated-links",
        "next-section",
    ):
        parser.add_argument(
            f"--{name}",
            required=True,
        )

    parser.add_argument(
        "--apply",
        action="store_true",
    )

    args = parser.parse_args()

    result = remove_redundant_continuation_header(
        source_path=args.source,
        output_path=args.output,
        identity=args.identity,
        repeated_heading=args.repeated_heading,
        repeated_links=args.repeated_links,
        next_section=args.next_section,
        dry_run=not args.apply,
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
