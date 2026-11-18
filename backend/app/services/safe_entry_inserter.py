
"""Safely insert approved entries into an existing DOCX preview."""

import argparse
import json
import re

from calendar import month_abbr
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from backend.app.models.resume_document import ResumeDocument
from backend.app.services.profile_store import PROFILE_PATH
from backend.app.services.snapshot_semantic_recheck import (
    document_hash,
)


def _find_paragraph(
    document,
    text: str,
    *,
    prefix: bool = False,
) -> Paragraph:
    target = text.strip().casefold()
    matches = []

    for paragraph in document.paragraphs:
        value = paragraph.text.strip().casefold()

        if (
            value.startswith(target)
            if prefix
            else value == target
        ):
            matches.append(paragraph)

    if len(matches) != 1:
        raise ValueError(
            f"Expected one paragraph for {text!r}; "
            f"found {len(matches)}."
        )

    return matches[0]


def _ensure_text_only(paragraph: Paragraph) -> None:
    forbidden = (
        ".//w:hyperlink",
        ".//w:fldChar",
        ".//w:instrText",
        ".//w:drawing",
        ".//w:object",
        ".//w:sectPr",
        ".//w:br",
        ".//w:bookmarkStart",
        ".//w:commentRangeStart",
    )

    if any(
        paragraph._p.xpath(query)
        for query in forbidden
    ):
        raise ValueError(
            "Unsafe prototype paragraph: "
            f"{paragraph.text[:60]!r}"
        )

    if (
        not paragraph.runs
        or not any(run.text for run in paragraph.runs)
    ):
        raise ValueError(
            "Prototype needs editable text runs."
        )


def _copy_after(
    prototype: Paragraph,
    after: Paragraph,
) -> Paragraph:
    element = deepcopy(prototype._p)

    after._p.addnext(element)

    return Paragraph(element, after._parent)


def _format_date(raw: object) -> str:
    value = str(raw or "").strip()

    if not value:
        return ""

    match = re.fullmatch(
        r"(\d{4})-(0[1-9]|1[0-2])(?:-\d{2})?",
        value,
    )

    if match:
        month = month_abbr[int(match.group(2))]
        return f"{month} {match.group(1)}"

    if any(char in value for char in "\r\n\t\x00"):
        raise ValueError("Unsafe date metadata.")

    return value


def _dates(work: dict) -> str:
    start = _format_date(work.get("start_date"))
    end = _format_date(work.get("end_date"))

    return " – ".join(
        value for value in (start, end) if value
    )


def _set_heading(
    paragraph: Paragraph,
    title: str,
    date: str,
) -> None:
    _ensure_text_only(paragraph)

    runs = paragraph.runs

    # Preserve original bold heading run.
    runs[0].text = title

    # Preserve separate date run and tab alignment.
    if date:
        if len(runs) >= 2:
            runs[1].text = "\t" + date
        else:
            runs[0].text += "\t" + date

    elif len(runs) >= 2:
        runs[1].text = ""

    for run in runs[2:]:
        run.text = ""


def _set_bullet(
    paragraph: Paragraph,
    text: str,
) -> None:
    _ensure_text_only(paragraph)

    if not (
        isinstance(text, str)
        and 10 <= len(text) <= 1200
        and text == text.strip()
        and not any(
            char in text for char in "\r\n\t\x00"
        )
        and not text.startswith(("• ", "- ", "– "))
    ):
        raise ValueError(
            "Unsafe generated bullet text."
        )

    runs = paragraph.runs

    if (
        len(runs) < 2
        or runs[0].text not in ("• ", "- ", "– ")
    ):
        raise ValueError(
            "Bullet prototype must have separate "
            "marker and body runs."
        )

    runs[1].text = text

    for run in runs[2:]:
        run.text = ""


def _bullet_prototype(
    document,
    heading: Paragraph,
) -> Paragraph:
    paragraphs = document.paragraphs

    for index, paragraph in enumerate(paragraphs):
        if paragraph._p is heading._p:
            if index + 1 < len(paragraphs):
                following = paragraphs[index + 1]

                if following.text.startswith(
                    ("• ", "- ", "– ")
                ):
                    return following

            break

    raise ValueError(
        "No immediately following bullet "
        f"for heading {heading.text!r}."
    )


def _body_sequence(
    document,
) -> list[tuple[str, str]]:
    result = []

    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            result.append(("p", item.text))

        elif isinstance(item, Table):
            table_text = "\n".join(
                cell.text
                for row in item.rows
                for cell in row.cells
            )

            result.append(("t", table_text))

        else:
            raise ValueError(
                "Unsupported DOCX body element."
            )

    return result


def insert_missing_approved_entries(
    *,
    source_path: str | Path,
    snapshot_path: str | Path,
    output_path: str | Path,
    work_ids: list[str],
    experience_anchor: str,
    project_anchor: str,
    experience_style_from: str,
    project_style_from: str,
    dry_run: bool = True,
) -> dict:
    source = Path(source_path)
    output = Path(output_path)

    if not source.is_file():
        raise FileNotFoundError(source)

    if source.resolve() == output.resolve():
        raise ValueError(
            "Source and output must differ."
        )

    if not work_ids or len(work_ids) != len(
        set(work_ids)
    ):
        raise ValueError(
            "Work IDs must be unique and nonempty."
        )

    if output.exists() and not dry_run:
        raise FileExistsError(
            f"Output already exists: {output}"
        )

    # 1. Verify approved snapshot.
    snapshot = json.loads(
        Path(snapshot_path).read_text(
            encoding="utf-8"
        )
    )

    recheck = snapshot.get(
        "semantic_recheck"
    ) or {}

    if not (
        snapshot.get("quality_passed") is True
        and snapshot.get("run_status")
        == "rechecked_approved"
        and recheck.get("passed") is True
        and recheck.get("document_sha256")
        == document_hash(snapshot["resume_document"])
    ):
        raise ValueError(
            "Snapshot lacks valid semantic approval."
        )

    # 2. Verify master profile.
    profile_bytes = Path(
        PROFILE_PATH
    ).read_bytes()

    if (
        sha256(profile_bytes).hexdigest()
        != snapshot.get("profile_sha256")
    ):
        raise ValueError(
            "Master profile SHA-256 mismatch."
        )

    profile = json.loads(
        profile_bytes.decode("utf-8-sig")
    )

    works = {
        work["id"]: work
        for work in profile["work_items"]
    }

    if len(works) != len(profile["work_items"]):
        raise ValueError(
            "Duplicate work IDs in master profile."
        )

    resume = ResumeDocument.model_validate(
        snapshot["resume_document"]
    )

    entries = {
        entry.work_id: entry
        for entry in resume.entries
    }

    if len(entries) != len(resume.entries):
        raise ValueError(
            "Duplicate approved work entries."
        )

    selected = set(
        snapshot["selected_fact_ids"]
    )

    # 3. Load existing working DOCX preview.
    document = Document(source)

    anchors = {
        "experience": _find_paragraph(
            document,
            experience_anchor,
        ),
        "project": _find_paragraph(
            document,
            project_anchor,
        ),
    }

    if (
        anchors["experience"]._p
        is anchors["project"]._p
    ):
        raise ValueError(
            "Experience/project anchors must differ."
        )

    # 4. Get template-native paragraph examples.
    prototypes = {
        "experience": _find_paragraph(
            document,
            experience_style_from,
            prefix=True,
        ),
        "project": _find_paragraph(
            document,
            project_style_from,
            prefix=True,
        ),
    }

    bullet_prototypes = {
        section: _bullet_prototype(
            document,
            heading,
        )
        for section, heading in prototypes.items()
    }

    for paragraph in (
        list(prototypes.values())
        + list(bullet_prototypes.values())
    ):
        _ensure_text_only(paragraph)

    original_hash = sha256(
        source.read_bytes()
    ).hexdigest()

    original_sequence = _body_sequence(document)

    original_titles = {
        paragraph.text.split("\t", 1)[0]
        .strip()
        .casefold()
        for paragraph in document.paragraphs
    }

    planned = []
    warnings = []
    new_titles = set()

    # 5. Validate all requested new entries.
    for work_id in work_ids:
        entry = entries.get(work_id)
        work = works.get(work_id)

        if entry is None or work is None:
            raise ValueError(
                f"Unknown or unapproved work ID: "
                f"{work_id}"
            )

        category = str(
            work.get("category") or ""
        ).lower()

        expected = (
            "experience"
            if category in {"job", "internship"}
            else "project"
            if category == "project"
            else None
        )

        if (
            expected is None
            or entry.section != expected
        ):
            raise ValueError(
                f"Section mismatch: {work_id}"
            )

        valid_facts = {
            fact["id"]
            for fact in work.get("facts", [])
        }

        if not entry.bullets:
            raise ValueError(
                f"No approved bullets: {work_id}"
            )

        bullet_texts = []

        for bullet in entry.bullets:
            if (
                bullet.fact_id not in valid_facts
                or bullet.fact_id not in selected
            ):
                raise ValueError(
                    "Unsupported fact: "
                    f"{work_id}/{bullet.fact_id}"
                )

            text = bullet.text

            if not (
                isinstance(text, str)
                and 10 <= len(text) <= 1200
                and text == text.strip()
                and not any(
                    char in text
                    for char in "\r\n\t\x00"
                )
                and not text.startswith(
                    ("• ", "- ", "– ")
                )
            ):
                raise ValueError(
                    f"Unsafe bullet in {work_id}."
                )

            bullet_texts.append(text)

        # 6. Use authoritative career metadata.
        if expected == "experience":
            company = str(
                work.get("organization") or ""
            ).strip()

            role = str(
                work.get("role") or ""
            ).strip()

            if not company:
                raise ValueError(
                    "Missing verified employer: "
                    f"{work_id}"
                )

            if (
                not role
                or "needs confirmation" in role.casefold()
            ):
                title = company

                warnings.append(
                    f"{work_id}: job title needs "
                    "verification. Company-only "
                    "heading is preview-only."
                )

            else:
                title = f"{role} — {company}"

        else:
            title = str(
                work.get("name") or ""
            ).strip()

        if (
            not title
            or any(
                char in title
                for char in "\r\n\t\x00"
            )
        ):
            raise ValueError(
                f"Missing/unsafe heading: {work_id}"
            )

        if (
            title.casefold() in original_titles
            or title.casefold() in new_titles
        ):
            raise ValueError(
                f"Heading already exists: {title}"
            )

        original_names = {
            value.casefold()
            for value in (
                title,
                str(work.get("name") or "").strip(),
            )
            if value
        }

        if original_titles.intersection(
            original_names
        ):
            raise ValueError(
                f"Equivalent heading already exists: "
                f"{work_id}"
            )

        new_titles.add(title.casefold())

        planned.append({
            "work_id": work_id,
            "section": expected,
            "title": title,
            "date": _dates(work),
            "bullets": bullet_texts,
        })

    result = {
        "preview_only": True,
        "dry_run": dry_run,
        "source": str(source),
        "output": (
            None if dry_run else str(output)
        ),
        "planned_work_ids": work_ids,
        "inserted_work_ids": [],
        "warnings": warnings,
        "existing_content_preserved": True,
        "visual_layout_verified": False,
    }

    # 7. Dry-run: inspect without writing.
    if dry_run:
        result["planned_entries"] = [
            {
                "work_id": item["work_id"],
                "section": item["section"],
                "title": item["title"],
                "date": item["date"],
                "bullet_count": len(item["bullets"]),
            }
            for item in planned
        ]

        return result

    # 8. Insert new entries after section anchors.
    last_in_section = dict(anchors)

    inserted_by_anchor = {
        anchors["experience"].text: [],
        anchors["project"].text: [],
    }

    for item in planned:
        section = item["section"]

        after = last_in_section[section]

        heading = _copy_after(
            prototypes[section],
            after,
        )

        _set_heading(
            heading,
            item["title"],
            item["date"],
        )

        inserted_by_anchor[
            anchors[section].text
        ].append(
            ("p", heading.text)
        )

        after = heading

        for bullet_text in item["bullets"]:
            new_bullet = _copy_after(
                bullet_prototypes[section],
                after,
            )

            _set_bullet(
                new_bullet,
                bullet_text,
            )

            inserted_by_anchor[
                anchors[section].text
            ].append(
                ("p", new_bullet.text)
            )

            after = new_bullet

        last_in_section[section] = after

        result["inserted_work_ids"].append(
            item["work_id"]
        )

    # 9. Build expected document structure.
    expected_sequence = []

    for kind, text in original_sequence:
        expected_sequence.append(
            (kind, text)
        )

        if (
            kind == "p"
            and text in inserted_by_anchor
        ):
            expected_sequence.extend(
                inserted_by_anchor[text]
            )

    if (
        sha256(source.read_bytes()).hexdigest()
        != original_hash
    ):
        raise ValueError(
            "Source DOCX changed during insertion."
        )

    # 10. Save to a temporary file and verify.
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with NamedTemporaryFile(
        dir=output.parent,
        prefix=".insert-preview-",
        suffix=".docx",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)

    try:
        document.save(temporary)

        reopened = Document(temporary)

        actual_sequence = _body_sequence(
            reopened
        )

        if actual_sequence != expected_sequence:
            raise ValueError(
                "Saved DOCX structure/text "
                "verification failed."
            )

        if output.exists():
            raise FileExistsError(
                f"Output already exists: {output}"
            )

        temporary.replace(output)

    finally:
        temporary.unlink(
            missing_ok=True
        )

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Insert missing approved CV entries "
            "without rebuilding the original DOCX."
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
        "--output",
        required=True,
    )

    parser.add_argument(
        "--work-ids",
        nargs="+",
        required=True,
    )

    parser.add_argument(
        "--experience-anchor",
        required=True,
    )

    parser.add_argument(
        "--project-anchor",
        required=True,
    )

    parser.add_argument(
        "--experience-style-from",
        required=True,
    )

    parser.add_argument(
        "--project-style-from",
        required=True,
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Write the DOCX. Without this flag, "
            "only run validation."
        ),
    )

    args = parser.parse_args()

    result = insert_missing_approved_entries(
        source_path=args.source,
        snapshot_path=args.snapshot,
        output_path=args.output,
        work_ids=args.work_ids,
        experience_anchor=args.experience_anchor,
        project_anchor=args.project_anchor,
        experience_style_from=(
            args.experience_style_from
        ),
        project_style_from=(
            args.project_style_from
        ),
        dry_run=not args.apply,
    )

    print(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
