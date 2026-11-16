
from pathlib import Path
from typing import Any

from docx import Document

from backend.app.models.resume_document import ResumeDocument
from backend.app.services.resume_grounding import (
    validate_resume_document,
)


INLINE_FIELDS = {
    "NAME",
    "HEADLINE",
    "CONTACT",
    "SUMMARY",
}

BLOCK_FIELDS = {
    "SKILLS",
    "EXPERIENCE",
    "PROJECTS",
    "EDUCATION",
}

ALL_FIELDS = INLINE_FIELDS | BLOCK_FIELDS


def _paragraphs(container):
    # Paragraphs directly inside a document or cell.
    yield from container.paragraphs

    # Paragraphs inside Word tables.
    for table in container.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from _paragraphs(cell)


def _all_paragraphs(document):
    yield from _paragraphs(document)

    # Also inspect headers and footers.
    for section in document.sections:
        yield from _paragraphs(section.header)
        yield from _paragraphs(section.footer)


def _validate_template(document):
    paragraphs = list(_all_paragraphs(document))

    for field in ALL_FIELDS:
        marker = "{{" + field + "}}"

        count = sum(
            p.text.count(marker)
            for p in paragraphs
        )

        if count != 1:
            raise ValueError(
                f"Expected exactly one {marker}; "
                f"found {count}"
            )

        if field in BLOCK_FIELDS:
            anchor = next(
                p for p in paragraphs
                if marker in p.text
            )

            if anchor.text.strip() != marker:
                raise ValueError(
                    f"{marker} must be alone "
                    "in its paragraph"
                )


def _replace_inline(paragraph, marker, value):
    """
    Replace a marker even when Word splits it
    across multiple runs.
    """
    while True:
        runs = paragraph.runs
        full_text = "".join(run.text for run in runs)

        start = full_text.find(marker)

        if start < 0:
            break

        end = start + len(marker)

        # Map character positions to Word runs.
        positions = []
        for run_index, run in enumerate(runs):
            for char_index in range(len(run.text)):
                positions.append((run_index, char_index))

        start_run, start_offset = positions[start]
        end_run, end_offset = positions[end - 1]

        before = runs[start_run].text[:start_offset]
        after = runs[end_run].text[end_offset + 1:]

        if start_run == end_run:
            runs[start_run].text = (
                before + value + after
            )
        else:
            runs[start_run].text = before + value

            for index in range(
                start_run + 1, end_run
            ):
                runs[index].text = ""

            runs[end_run].text = after


def _style(document, preferred, fallback="Normal"):
    try:
        document.styles[preferred]
        return preferred
    except KeyError:
        return fallback


def _add_before(
    document,
    anchor,
    text,
    style_name="Normal",
):
    return anchor.insert_paragraph_before(
        text,
        style=_style(document, style_name),
    )


def _remove_paragraph(paragraph):
    element = paragraph._element
    element.getparent().remove(element)


def _contact_line(candidate):
    values = []

    for key in (
        "email", "phone",
        "github", "linkedin", "portfolio",
    ):
        value = candidate.get(key)
        if value:
            values.append(str(value))

    return " | ".join(values)


def _insert_skills(document, anchor, resume):
    for group in resume.skill_groups:
        paragraph = _add_before(
            document, anchor, "",
            "CV Skills",
        )

        paragraph.add_run(
            f"{group.title}: "
        ).bold = True

        paragraph.add_run(
            ", ".join(group.skills)
        )


def _entry_heading(work, section_name):
    if section_name == "experience":
        title = (
            work.get("organization")
            or work["name"]
        )
    else:
        title = work["name"]

    role = work.get("role")

    if role and role.casefold() not in title.casefold():
        title += f" — {role}"

    return title


def _insert_entries(
    document,
    anchor,
    resume,
    context,
    section_name,
):
    work_lookup = {
        work["id"]: work
        for work in context["work_items"]
    }

    for entry in resume.entries:
        if entry.section != section_name:
            continue

        work = work_lookup[entry.work_id]

        _add_before(
            document,
            anchor,
            _entry_heading(work, section_name),
            "CV Entry",
        )

        start = work.get("start_date")
        end = work.get("end_date")

        dates = " – ".join(
            str(value)
            for value in (start, end)
            if value
        )

        if dates:
            _add_before(
                document,
                anchor,
                dates,
                "CV Dates",
            )

        for bullet in entry.bullets:
            _add_before(
                document,
                anchor,
                bullet.text,
                "CV Bullet",
            )


def _insert_education(document, anchor, context):
    education = (
        context["candidate"].get("education")
        or []
    )

    if isinstance(education, dict):
        education = [education]

    for item in education:
        if not isinstance(item, dict):
            continue

        degree = item.get("degree")
        institution = item.get("institution")

        heading = " — ".join(
            str(value)
            for value in (degree, institution)
            if value
        )

        if heading:
            _add_before(
                document,
                anchor,
                heading,
                "CV Entry",
            )

        details = []

        if item.get("graduation_year"):
            details.append(
                f"Graduation: {item['graduation_year']}"
            )

        if item.get("cgpa") is not None:
            details.append(
                f"CGPA: {item['cgpa']}"
            )

        if details:
            _add_before(
                document,
                anchor,
                " | ".join(details),
                "CV Dates",
            )


def export_resume_docx(
    resume: ResumeDocument,
    context: dict[str, Any],
    template_path: str | Path,
    output_path: str | Path,
) -> Path:

    # Validate structured resume before export.
    errors = validate_resume_document(
        resume, context
    )

    if errors:
        raise ValueError(
            "Invalid resume:\n" + "\n".join(errors)
        )

    template_path = Path(template_path)
    output_path = Path(output_path)

    if not template_path.is_file():
        raise FileNotFoundError(template_path)

    document = Document(template_path)
    _validate_template(document)

    candidate = context["candidate"]

    inline_values = {
        "NAME": candidate["name"],
        "HEADLINE": resume.headline,
        "CONTACT": _contact_line(candidate),
        "SUMMARY": resume.summary,
    }

    # Replace inline placeholders.
    for paragraph in list(_all_paragraphs(document)):
        for field, value in inline_values.items():
            _replace_inline(
                paragraph,
                "{{" + field + "}}",
                str(value),
            )

    # Expand section placeholders.
    for field in (
        "SKILLS",
        "EXPERIENCE",
        "PROJECTS",
        "EDUCATION",
    ):
        marker = "{{" + field + "}}"

        anchor = next(
            p for p in _all_paragraphs(document)
            if p.text.strip() == marker
        )

        if field == "SKILLS":
            _insert_skills(document, anchor, resume)

        elif field == "EXPERIENCE":
            _insert_entries(
                document, anchor, resume,
                context, "experience"
            )

        elif field == "PROJECTS":
            _insert_entries(
                document, anchor, resume,
                context, "project"
            )

        elif field == "EDUCATION":
            _insert_education(
                document, anchor, context
            )

        _remove_paragraph(anchor)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    document.save(output_path)

    return output_path
