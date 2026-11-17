from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

from docx import Document
from docx.text.paragraph import Paragraph

from backend.app.models.template_edit_plan import TemplateEditPlan
from backend.app.models.template_mapping import TemplateMapping
from backend.app.services.template_edit_planner import (
    BULLET_PREFIXES,
    validate_edit_plan,
)
from backend.app.services.template_inspector import inspect_template


def _body_paragraphs(document) -> dict[str, Paragraph]:
    result = {}
    for position, item in enumerate(document.iter_inner_content()):
        if isinstance(item, Paragraph) and item.text.strip():
            result[f"body/{position}"] = item
    return result


def _check_text_only_runs(paragraph: Paragraph) -> None:
    for element in paragraph._p:
        if element.tag.rsplit("}", 1)[-1] not in {"pPr", "r"}:
            raise ValueError("Target paragraph contains unsupported Word elements.")

    for run in paragraph.runs:
        for element in run._r:
            if element.tag.rsplit("}", 1)[-1] not in {"rPr", "t"}:
                raise ValueError("Target run contains non-text elements.")


def _replace_plain(paragraph: Paragraph, new_text: str) -> None:
    _check_text_only_runs(paragraph)
    if len(paragraph.runs) != 1:
        raise ValueError(
            "Target paragraph has multiple runs or hyperlinks; manual review is required."
        )
    paragraph.runs[0].text = new_text


def _run_format_xml(run) -> str | None:
    run_properties = run._r.rPr
    return run_properties.xml if run_properties is not None else None


def _replace_bullet(paragraph: Paragraph, new_body: str) -> None:
    _check_text_only_runs(paragraph)
    runs = paragraph.runs
    if len(runs) < 2 or runs[0].text not in BULLET_PREFIXES:
        raise ValueError(
            "Bullet must have a standalone marker run and at least one body run."
        )

    body_runs = runs[1:]
    if not body_runs[0].text or not all(run.text for run in body_runs):
        raise ValueError("Bullet contains empty or unsupported body runs.")

    first_format = _run_format_xml(body_runs[0])
    if any(_run_format_xml(run) != first_format for run in body_runs[1:]):
        raise ValueError("Bullet body contains mixed formatting; review required.")

    # Keep the bullet marker and its formatting unchanged.
    # Change only the first body run; clear other *uniform* text runs.
    body_runs[0].text = new_body
    for run in body_runs[1:]:
        run.text = ""


def apply_template_edit_plan(
    template_path: str | Path,
    output_path: str | Path,
    mapping: TemplateMapping,
    plan: TemplateEditPlan,
) -> Path:
    source = Path(template_path)
    destination = Path(output_path)

    if source.resolve() == destination.resolve():
        raise ValueError("Output must differ from the original template.")
    if destination.exists():
        raise FileExistsError(f"Output already exists: {destination}")

    report = inspect_template(source)
    errors = validate_edit_plan(report, mapping, plan)
    if errors:
        raise ValueError("Unsafe edit plan: " + "; ".join(errors))

    document = Document(source)
    paragraphs = _body_paragraphs(document)
    original_texts = {
        block_id: paragraph.text
        for block_id, paragraph in paragraphs.items()
    }

    for edit in plan.edits:
        paragraph = paragraphs.get(edit.block_id)
        if paragraph is None or paragraph.text != edit.old_text:
            raise ValueError(f"Target paragraph changed: {edit.block_id}")
        if edit.mode == "bullet":
            _replace_bullet(paragraph, edit.new_text)
        else:
            _replace_plain(paragraph, edit.new_text)

    if sha256(source.read_bytes()).hexdigest() != plan.template_sha256:
        raise ValueError("Template changed during editing.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        dir=destination.parent,
        prefix=".cv-edit-",
        suffix=".docx",
        delete=False,
    ) as handle:
        temporary_path = Path(handle.name)

    try:
        document.save(temporary_path)
        verified = _body_paragraphs(Document(temporary_path))
        edits_by_id = {edit.block_id: edit for edit in plan.edits}

        if set(verified) != set(original_texts):
            raise ValueError("DOCX paragraph structure changed unexpectedly.")

        for block_id, original in original_texts.items():
            edit = edits_by_id.get(block_id)
            if edit is None:
                expected = original
            elif edit.mode == "bullet":
                marker = original[:2]
                expected = marker + edit.new_text
            else:
                expected = edit.new_text
            if verified[block_id].text != expected:
                raise ValueError(f"Unexpected text change: {block_id}")

        if destination.exists():
            raise FileExistsError(f"Output already exists: {destination}")
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)

    return destination
