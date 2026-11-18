
"""Conservative, explicitly scoped DOCX entry removal.

Entries are never selected for deletion merely because
they are absent from the generated ResumeDocument.

Requires exact titles, section boundaries, a valid
approved snapshot, and safe contiguous paragraph blocks.
"""

import json
import re

from collections import Counter
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from backend.app.models.entry_removal_plan import (
    EntryRemovalPlan,
    RemovalTarget,
)
from backend.app.models.resume_document import (
    ResumeDocument,
)
from backend.app.services.profile_store import (
    PROFILE_PATH,
)
from backend.app.services.snapshot_semantic_recheck import (
    document_hash,
)


_MARKERS = ("• ", "- ", "– ")

_UNSAFE_XML = (
    ".//w:hyperlink",
    ".//w:drawing",
    ".//w:object",
    ".//w:fldChar",
    ".//w:instrText",
    ".//w:sectPr",
    ".//w:br",
    ".//w:bookmarkStart",
    ".//w:bookmarkEnd",
    ".//w:commentRangeStart",
    ".//w:commentRangeEnd",
    ".//w:pageBreakBefore",
)


def _compact(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip().casefold()


def _label(paragraph: Paragraph) -> str:
    # Word templates often separate title
    # and right-aligned date using a tab.
    return paragraph.text.split(
        "\t", 1
    )[0].strip()


def _unique_heading(
    paragraphs: list[Paragraph],
    title: str,
) -> int:
    positions = [
        index
        for index, paragraph
        in enumerate(paragraphs)
        if _compact(_label(paragraph))
        == _compact(title)
    ]

    if len(positions) != 1:
        raise ValueError(
            f"Section boundary {title!r} must "
            f"be unique; found {len(positions)}."
        )

    return positions[0]


def _body_sequence(document) -> list[tuple[str, str]]:
    result = []

    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            result.append(
                ("paragraph", item.text)
            )

        elif isinstance(item, Table):
            table_text = "\n".join(
                cell.text
                for row in item.rows
                for cell in row.cells
            )

            result.append(
                ("table", table_text)
            )

        else:
            raise ValueError(
                "Unsupported Word body element."
            )

    return result


def _verified_snapshot(
    snapshot_path: str | Path,
) -> tuple[ResumeDocument, dict]:
    data = json.loads(
        Path(snapshot_path).read_text(
            encoding="utf-8"
        )
    )

    approval = data.get(
        "semantic_recheck"
    ) or {}

    if not (
        data.get("quality_passed") is True
        and data.get("run_status")
        == "rechecked_approved"
        and approval.get("passed") is True
        and approval.get("document_sha256")
        == document_hash(
            data["resume_document"]
        )
    ):
        raise ValueError(
            "No valid semantic approval "
            "or document fingerprint."
        )

    actual_profile_hash = sha256(
        Path(PROFILE_PATH).read_bytes()
    ).hexdigest()

    if (
        actual_profile_hash
        != data.get("profile_sha256")
    ):
        raise ValueError(
            "Master profile hash differs "
            "from approved snapshot."
        )

    resume = ResumeDocument.model_validate(
        data["resume_document"]
    )

    work_ids = [
        entry.work_id
        for entry in resume.entries
    ]

    if len(work_ids) != len(set(work_ids)):
        raise ValueError(
            "Duplicate approved work IDs."
        )

    selected = data.get(
        "selected_fact_ids"
    )

    if (
        not isinstance(selected, list)
        or len(selected) != len(set(selected))
    ):
        raise ValueError(
            "Invalid selected fact IDs."
        )

    for entry in resume.entries:
        for bullet in entry.bullets:
            if bullet.fact_id not in selected:
                raise ValueError(
                    "Approved bullet is not selected: "
                    f"{bullet.fact_id}"
                )

    profile = json.loads(
        Path(PROFILE_PATH).read_text(
            encoding="utf-8-sig"
        )
    )

    return resume, profile


def _approved_bullets(
    resume: ResumeDocument,
) -> Counter:
    return Counter(
        _compact(bullet.text)
        for entry in resume.entries
        for bullet in entry.bullets
    )


def _present_bullets(document) -> Counter:
    return Counter(
        _compact(paragraph.text[2:])
        for paragraph in document.paragraphs
        if paragraph.text.startswith(_MARKERS)
    )


def _approved_titles(
    resume: ResumeDocument,
    profile: dict,
) -> set[str]:
    approved_ids = {
        entry.work_id
        for entry in resume.entries
    }

    titles: set[str] = set()

    for work in profile.get(
        "work_items", []
    ):
        if work.get("id") not in approved_ids:
            continue

        for key in (
            "name",
            "organization",
        ):
            value = work.get(key)

            if (
                isinstance(value, str)
                and value.strip()
            ):
                titles.add(_compact(value))

        role = work.get("role")
        organization = work.get("organization")

        if role and organization:
            titles.add(
                _compact(
                    f"{role} — {organization}"
                )
            )

            titles.add(
                _compact(
                    f"{organization} — {role}"
                )
            )

    return titles


def _plain_paragraph(
    paragraph: Paragraph,
) -> bool:
    if (
        paragraph._p.getparent().tag
        != qn("w:body")
    ):
        return False

    return not any(
        paragraph._p.xpath(query)
        for query in _UNSAFE_XML
    )


def _xml_adjacent(
    paragraphs: list[Paragraph],
    positions: list[int],
) -> bool:
    """Reject hidden tables between entry paragraphs."""
    return all(
        paragraphs[left]._p.getnext()
        is paragraphs[right]._p
        for left, right in zip(
            positions,
            positions[1:],
        )
    )


def plan_entry_removal(
    *,
    source_path: str | Path,
    snapshot_path: str | Path,
    section_start: str,
    section_end: str,
    remove_titles: list[str],
) -> EntryRemovalPlan:
    """
    Build a read-only removal plan.

    Nothing is deleted or written here.
    """

    if (
        not remove_titles
        or len({
            _compact(value)
            for value in remove_titles
        }) != len(remove_titles)
    ):
        raise ValueError(
            "Provide unique, nonempty "
            "removal titles."
        )

    if any(
        not title.strip()
        for title in remove_titles
    ):
        raise ValueError(
            "Removal titles must be nonempty."
        )

    source = Path(source_path)

    if not source.is_file():
        raise FileNotFoundError(source)

    resume, profile = _verified_snapshot(
        snapshot_path
    )

    document = Document(source)
    paragraphs = document.paragraphs

    start = _unique_heading(
        paragraphs,
        section_start,
    )

    end = _unique_heading(
        paragraphs,
        section_end,
    )

    if end <= start:
        raise ValueError(
            "Section end must appear "
            "after section start."
        )

    # A removal source must already contain
    # every approved resume bullet.
    available = _present_bullets(document)
    required = _approved_bullets(resume)

    missing = required - available

    if missing:
        raise ValueError(
            "Source is missing approved resume "
            "bullets; run insertion first. "
            f"Missing count: {sum(missing.values())}"
        )

    protected_titles = _approved_titles(
        resume,
        profile,
    )

    targets = []
    selected_positions: set[int] = set()

    for title in remove_titles:
        matches = [
            index
            for index in range(
                start + 1,
                end,
            )
            if _compact(_label(paragraphs[index]))
            == _compact(title)
        ]

        if len(matches) != 1:
            raise ValueError(
                f"Removal heading {title!r} "
                "must occur once inside section; "
                f"found {len(matches)}."
            )

        position = matches[0]
        heading = paragraphs[position]

        bullet_indices = []
        cursor = position + 1

        while (
            cursor < end
            and paragraphs[cursor].text.startswith(
                _MARKERS
            )
        ):
            bullet_indices.append(cursor)
            cursor += 1

        reason = ""

        if (
            _compact(_label(heading))
            in protected_titles
        ):
            reason = (
                "Heading belongs to approved "
                "ResumeDocument."
            )

        elif not bullet_indices:
            reason = (
                "No contiguous bullet paragraphs "
                "immediately follow heading."
            )

        elif not all(
            _plain_paragraph(paragraphs[index])
            for index in [
                position,
                *bullet_indices,
            ]
        ):
            reason = (
                "Complex/protected Word XML "
                "in entry."
            )

        elif not _xml_adjacent(
            paragraphs,
            [position, *bullet_indices],
        ):
            reason = (
                "Entry paragraphs are separated "
                "by tables or other XML."
            )

        elif (
            paragraphs[
                bullet_indices[-1]
            ]._p.getnext() is not None
            and paragraphs[
                bullet_indices[-1]
            ]._p.getnext().tag
            == qn("w:tbl")
        ):
            reason = (
                "Table immediately follows entry "
                "bullets; scope is ambiguous."
            )

        else:
            # Do not accidentally leave supporting
            # notes or links behind.
            next_index = cursor

            while (
                next_index < end
                and not paragraphs[
                    next_index
                ].text.strip()
            ):
                next_index += 1

            if next_index < end:
                next_is_entry = (
                    next_index + 1 < end
                    and paragraphs[
                        next_index + 1
                    ].text.startswith(_MARKERS)
                )

                if not next_is_entry:
                    reason = (
                        "Unrecognized content after "
                        "bullets; refusing to leave "
                        "an orphaned note or hyperlink."
                    )

            # Never remove bullets belonging
            # to an approved resume entry.
            if (
                not reason
                and any(
                    _compact(
                        paragraphs[index].text[2:]
                    ) in required
                    for index in bullet_indices
                )
            ):
                reason = (
                    "Entry includes an approved "
                    "resume bullet."
                )

        positions = [
            position,
            *bullet_indices,
        ]

        if selected_positions.intersection(
            positions
        ):
            reason = (
                "Removal blocks overlap another "
                "requested entry."
            )

        selected_positions.update(positions)

        targets.append(
            RemovalTarget(
                title=title,
                heading_index=position,
                bullet_indices=bullet_indices,
                safe=not reason,
                reason=reason,
            )
        )

    return EntryRemovalPlan(
        source_path=str(source),
        source_sha256=sha256(
            source.read_bytes()
        ).hexdigest(),
        section_start=section_start,
        section_end=section_end,
        targets=targets,
        warnings=[
            f"{item.title}: {item.reason}"
            for item in targets
            if not item.safe
        ],
    )


def apply_entry_removal(
    *,
    source_path: str | Path,
    snapshot_path: str | Path,
    output_path: str | Path,
    section_start: str,
    section_end: str,
    remove_titles: list[str],
) -> dict:
    """
    Remove explicitly selected safe entries.

    Original DOCX is never overwritten.
    """

    source = Path(source_path)
    output = Path(output_path)

    if source.resolve() == output.resolve():
        raise ValueError(
            "Output must differ from source."
        )

    if output.exists():
        raise FileExistsError(
            f"Output already exists: {output}"
        )

    plan = plan_entry_removal(
        source_path=source,
        snapshot_path=snapshot_path,
        section_start=section_start,
        section_end=section_end,
        remove_titles=remove_titles,
    )

    if not plan.can_apply:
        raise ValueError(
            "Removal not safe: "
            + "; ".join(plan.warnings)
        )

    document = Document(source)
    paragraphs = document.paragraphs

    removed = set()

    for target in plan.targets:
        removed.update([
            target.heading_index,
            *target.bullet_indices,
        ])

    # Preserve every unrelated body element,
    # including tables and ordinary paragraphs.
    original_body = list(
        document.iter_inner_content()
    )

    elements_to_remove = {
        paragraphs[index]._p
        for index in removed
    }

    expected_sequence = []

    for item in original_body:
        if (
            isinstance(item, Paragraph)
            and item._p in elements_to_remove
        ):
            continue

        if isinstance(item, Paragraph):
            expected_sequence.append(
                ("paragraph", item.text)
            )

        elif isinstance(item, Table):
            expected_sequence.append(
                (
                    "table",
                    "\n".join(
                        cell.text
                        for row in item.rows
                        for cell in row.cells
                    ),
                )
            )

        else:
            raise ValueError(
                "Unsupported body object."
            )

    # Delete from the end to avoid index
    # shifting during removal.
    for index in sorted(
        removed,
        reverse=True,
    ):
        element = paragraphs[index]._p
        element.getparent().remove(
            element
        )

    current_hash = sha256(
        source.read_bytes()
    ).hexdigest()

    if current_hash != plan.source_sha256:
        raise ValueError(
            "Source changed while applying removal."
        )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with NamedTemporaryFile(
        dir=output.parent,
        prefix=".entry-removal-",
        suffix=".docx",
        delete=False,
    ) as handle:
        temporary = Path(
            handle.name
        )

    try:
        document.save(temporary)

        reopened = Document(temporary)

        if (
            _body_sequence(reopened)
            != expected_sequence
        ):
            raise ValueError(
                "DOCX structural comparison "
                "failed after save."
            )

        resume, _ = _verified_snapshot(
            snapshot_path
        )

        if (
            _approved_bullets(resume)
            - _present_bullets(reopened)
        ):
            raise ValueError(
                "Approved resume bullet lost "
                "during removal."
            )

        if (
            sha256(
                source.read_bytes()
            ).hexdigest()
            != plan.source_sha256
        ):
            raise ValueError(
                "Source changed before publication."
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

    return {
        "output": str(output),
        "removed_titles": remove_titles,
        "removed_paragraph_count": len(removed),
        "source_unchanged": True,
        "approved_bullets_preserved": True,
        "preview_only": True,
        "visual_layout_verified": False,
    }
