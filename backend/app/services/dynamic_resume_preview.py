
import json

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from backend.app.models.resume_document import (
    ResumeDocument,
)
from backend.app.services.profile_store import (
    PROFILE_PATH,
    load_profile,
)
from backend.app.services.snapshot_semantic_recheck import (
    document_hash,
)
from backend.app.services.template_editor import (
    _body_paragraphs,
    _check_text_only_runs,
    _replace_bullet,
    _replace_plain,
    _run_format_xml,
)
from backend.app.services.template_entry_matcher import (
    map_template_entries,
)
from backend.app.services.template_inspector import (
    inspect_template,
)
from backend.app.services.template_mapper import (
    map_template,
)


def _sequence(
    document,
) -> list[tuple[str, str]]:
    """
    Capture top-level Word body structure
    in its original order.
    """

    items = []

    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            items.append(
                ("paragraph", item.text)
            )

        elif isinstance(item, Table):
            text = "\n".join(
                cell.text
                for row in item.rows
                for cell in row.cells
            )

            items.append(
                ("table", text)
            )

        else:
            raise ValueError(
                "Unsupported Word body element."
            )

    return items


def _clean_bullet(text: str) -> bool:
    return (
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
    )


def write_dynamic_resume_preview(
    template_path: str | Path,
    snapshot_path: str | Path,
    output_path: str | Path,
) -> dict:
    """
    Update existing approved template entries.

    Supports adding/removing bullet paragraphs.
    Does not invent or insert new work entries.
    """

    source = Path(template_path)
    output = Path(output_path)

    if source.resolve() == output.resolve():
        raise ValueError(
            "Output must differ from "
            "original template."
        )

    if output.exists():
        raise FileExistsError(
            f"Output already exists: {output}"
        )

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
    ):
        raise ValueError(
            "Snapshot has no successful "
            "semantic recheck."
        )

    if (
        recheck.get("document_sha256")
        != document_hash(
            snapshot["resume_document"]
        )
    ):
        raise ValueError(
            "Resume content changed after "
            "semantic recheck."
        )

    if (
        sha256(
            PROFILE_PATH.read_bytes()
        ).hexdigest()
        != snapshot.get("profile_sha256")
    ):
        raise ValueError(
            "Master profile hash changed "
            "after evaluation."
        )

    resume = ResumeDocument.model_validate(
        snapshot["resume_document"]
    )

    selected = set(
        snapshot.get("selected_fact_ids", [])
    )

    profile = load_profile()

    works = {
        item.id: item
        for item in profile.work_items
    }

    report = inspect_template(source)
    mapping = map_template(report)

    entry_map = map_template_entries(
        report,
        mapping,
        profile.work_items,
    )

    doc = Document(source)
    paragraphs = _body_paragraphs(doc)

    original = _sequence(doc)

    protected = set(
        mapping.protected_block_ids
    )

    slots = {}

    for slot in entry_map.slots:
        if slot.work_id:
            slots.setdefault(
                slot.work_id, []
            ).append(slot)

    edits = []
    skipped = []
    updated_work_ids = []
    seen_work_ids = set()

    # STEP 1: Match generated entries to
    # approved original template slots.
    for entry in resume.entries:
        if entry.work_id in seen_work_ids:
            skipped.append(
                f"{entry.work_id}: duplicate work entry"
            )
            continue

        seen_work_ids.add(entry.work_id)

        work = works.get(entry.work_id)

        matches = slots.get(
            entry.work_id, []
        )

        if (
            work is None
            or len(matches) != 1
            or matches[0].needs_review
        ):
            skipped.append(
                f"{entry.work_id}: no unique "
                "approved template slot"
            )
            continue

        slot = matches[0]

        section = (
            "experience"
            if work.category in {
                "job", "internship"
            }
            else "projects"
            if work.category == "project"
            else None
        )

        expected_entry_section = (
            "experience"
            if section == "experience"
            else "project"
        )

        if (
            section is None
            or slot.section != section
            or entry.section
            != expected_entry_section
        ):
            skipped.append(
                f"{entry.work_id}: section mismatch"
            )
            continue

        valid_facts = {
            fact.id
            for fact in work.facts
        }

        if (
            not entry.bullets
            or len(entry.bullets) > 8
            or any(
                bullet.fact_id not in valid_facts
                or bullet.fact_id not in selected
                or not _clean_bullet(bullet.text)
                for bullet in entry.bullets
            )
        ):
            skipped.append(
                f"{entry.work_id}: unsupported "
                "fact or bullet text"
            )
            continue

        ids = slot.bullet_block_ids

        indexes = [
            int(block_id.split("/")[1])
            for block_id in ids
        ]

        if (
            not ids
            or indexes != list(
                range(
                    indexes[0],
                    indexes[0] + len(ids),
                )
            )
            or any(
                block_id in protected
                or block_id not in paragraphs
                for block_id in ids
            )
            or any(
                original[index][0] != "paragraph"
                for index in indexes
            )
        ):
            skipped.append(
                f"{entry.work_id}: unsafe or "
                "noncontiguous bullet location"
            )
            continue

        # There must be no unrelated content
        # between entry heading and its bullets.
        heading_pos = int(
            slot.heading_block_id.split("/")[1]
        )

        if indexes[0] != heading_pos + 1:
            skipped.append(
                f"{entry.work_id}: "
                "intervening entry content"
            )
            continue

        edits.append((
            ids,
            [
                bullet.text
                for bullet in entry.bullets
            ],
        ))

        updated_work_ids.append(
            entry.work_id
        )

    # STEP 2: Identify an editable summary.
    summary_id = None

    summaries = [
        region
        for region in mapping.regions
        if region.section == "summary"
    ]

    if (
        len(summaries) == 1
        and not summaries[0].needs_review
        and len(
            summaries[0].content_block_ids
        ) == 1
    ):
        candidate_id = (
            summaries[0].content_block_ids[0]
        )

        if (
            candidate_id in paragraphs
            and candidate_id not in protected
        ):
            summary_id = candidate_id

    if not edits and summary_id is None:
        raise ValueError(
            "No safely editable template content."
        )

    # STEP 3: Validate Word runs before
    # modifying any in-memory XML.
    for ids, new_bullets in edits:
        for block_id in ids:
            para = paragraphs[block_id]

            _check_text_only_runs(para)

            runs = para.runs

            if (
                len(runs) < 2
                or runs[0].text
                not in ("• ", "- ", "– ")
            ):
                raise ValueError(
                    "Unsupported bullet runs: "
                    f"{block_id}"
                )

            if (
                any(
                    not run.text
                    for run in runs[1:]
                )
                or any(
                    _run_format_xml(run)
                    != _run_format_xml(runs[1])
                    for run in runs[2:]
                )
            ):
                raise ValueError(
                    "Mixed or empty bullet "
                    f"body runs: {block_id}"
                )

    if summary_id:
        p = paragraphs[summary_id]

        _check_text_only_runs(p)

        if (
            len(p.runs) != 1
            or resume.summary
            != resume.summary.strip()
            or any(
                char in resume.summary
                for char in "\r\n\t\x00"
            )
        ):
            raise ValueError(
                "Unsupported summary paragraph."
            )

    # STEP 4: Build the expected final
    # body sequence for verification.
    replacements = {}
    skipped_positions = set()

    for ids, new_bullets in edits:
        positions = [
            int(block_id.split("/")[1])
            for block_id in ids
        ]

        markers = [
            paragraphs[block_id].runs[0].text
            for block_id in ids
        ]

        marker = markers[-1]

        replacements[positions[0]] = [
            (
                "paragraph",
                (
                    markers[index]
                    if index < len(markers)
                    else marker
                ) + text,
            )
            for index, text in enumerate(
                new_bullets
            )
        ]

        skipped_positions.update(
            positions[1:]
        )

    if summary_id:
        position = int(
            summary_id.split("/")[1]
        )

        replacements[position] = [
            ("paragraph", resume.summary)
        ]

    expected = []

    for position, item in enumerate(original):
        if position in replacements:
            expected.extend(
                replacements[position]
            )
        elif position not in skipped_positions:
            expected.append(item)

    # STEP 5: Clone new bullet paragraphs
    # or remove surplus bullet paragraphs.
    inserted = 0
    deleted = 0

    for ids, new_bullets in edits:
        old_paras = [
            paragraphs[block_id]
            for block_id in ids
        ]

        # Copy original XML BEFORE editing runs.
        pattern = deepcopy(
            old_paras[-1]._p
        )

        last = old_paras[-1]

        for index in range(
            len(ids),
            len(new_bullets),
        ):
            element = deepcopy(pattern)

            last._p.addnext(element)

            clone = Paragraph(
                element,
                last._parent,
            )

            _replace_bullet(
                clone,
                new_bullets[index],
            )

            last = clone
            inserted += 1

        # Replace existing bullets.
        for para, text in zip(
            old_paras,
            new_bullets,
        ):
            _replace_bullet(
                para,
                text,
            )

        # Delete original surplus bullets.
        for para in old_paras[
            len(new_bullets):
        ]:
            para._p.getparent().remove(
                para._p
            )

            deleted += 1

    if summary_id:
        _replace_plain(
            paragraphs[summary_id],
            resume.summary,
        )

    # STEP 6: Confirm source was unchanged.
    if (
        sha256(
            source.read_bytes()
        ).hexdigest()
        != report.sha256
    ):
        raise ValueError(
            "Template changed during editing."
        )

    # STEP 7: Write temporary DOCX,
    # reload and verify exact paragraph sequence.
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with NamedTemporaryFile(
        dir=output.parent,
        prefix=".cv-dynamic-",
        suffix=".docx",
        delete=False,
    ) as handle:
        temporary = Path(
            handle.name
        )

    try:
        doc.save(temporary)

        actual = _sequence(
            Document(temporary)
        )

        if actual != expected:
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

    return {
        "output": str(output),
        "updated_work_ids": updated_work_ids,
        "skipped": skipped,
        "bullets_inserted": inserted,
        "bullets_removed": deleted,
        "summary_updated": summary_id is not None,
        "unchanged_template_entries": [
            slot.heading_block_id
            for slot in entry_map.slots
            if slot.work_id
            not in set(updated_work_ids)
        ],
        "preview_only": True,
        "layout_verified": False,
    }
