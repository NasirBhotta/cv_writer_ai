
import hashlib
import re
import xml.etree.ElementTree as ET

from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from backend.app.models.template_report import (
    PageLayout,
    SectionHint,
    TemplateBlock,
    TemplateReport,
)


SECTION_NAMES = {
    "summary": {
        "summary",
        "professional summary",
        "profile",
        "about me",
    },
    "skills": {
        "skills",
        "technical skills",
        "core skills",
        "tech stack",
    },
    "experience": {
        "experience",
        "work experience",
        "professional experience",
        "employment history",
    },
    "projects": {
        "projects",
        "selected projects",
        "personal projects",
        "academic projects",
    },
    "education": {
        "education",
        "academic background",
        "qualifications",
    },
}


def _walk(
    container,
    prefix: str,
    blocks: list[TemplateBlock],
) -> None:
    """Visit paragraphs and table cells in document order."""

    for index, item in enumerate(
        container.iter_inner_content()
    ):
        position = f"{prefix}/{index}"

        if isinstance(item, Paragraph):
            text = item.text.strip()

            if not text:
                continue

            blocks.append(
                TemplateBlock(
                    block_id=position,
                    text=text,
                    style_name=(
                        item.style.name
                        if item.style
                        else "Normal"
                    ),
                    alignment=(
                        str(item.alignment)
                        if item.alignment is not None
                        else None
                    ),
                    font_names=sorted({
                        run.font.name
                        for run in item.runs
                        if run.font.name
                    }),
                    has_bold_run=any(
                        run.bold is True
                        for run in item.runs
                    ),
                )
            )

        elif isinstance(item, Table):
            # Merged cells can occupy multiple grid positions.
            seen_cells = set()

            for row_index, row in enumerate(item.rows):
                for cell_index, cell in enumerate(
                    row.cells
                ):
                    xml_cell_id = id(cell._tc)

                    if xml_cell_id in seen_cells:
                        continue

                    seen_cells.add(xml_cell_id)

                    _walk(
                        cell,
                        (
                            f"{position}/"
                            f"r{row_index}c{cell_index}"
                        ),
                        blocks,
                    )


def _layout(section) -> PageLayout:
    columns_element = section._sectPr.find(
        qn("w:cols")
    )

    raw_columns = (
        columns_element.get(qn("w:num"))
        if columns_element is not None
        else None
    )

    def inches(value):
        return (
            round(value.inches, 2)
            if value is not None
            else 0.0
        )

    return PageLayout(
        page_width_in=inches(section.page_width),
        page_height_in=inches(section.page_height),
        top_margin_in=inches(section.top_margin),
        bottom_margin_in=inches(section.bottom_margin),
        left_margin_in=inches(section.left_margin),
        right_margin_in=inches(section.right_margin),
        columns=int(raw_columns or 1),
    )


def _package_warnings(path: Path) -> list[str]:
    warnings = []

    w = (
        "{http://schemas.openxmlformats.org/"
        "wordprocessingml/2006/main}"
    )

    with ZipFile(path) as archive:
        members = archive.infolist()

        total_size = sum(
            member.file_size
            for member in members
        )

        if total_size > 100 * 1024 * 1024:
            raise ValueError(
                "DOCX uncompressed content exceeds 100 MB"
            )

        text_boxes = 0
        drawings = 0

        for member in members:
            name = member.filename

            if not re.fullmatch(
                r"word/(document|header\d+|footer\d+)\.xml",
                name,
            ):
                continue

            if member.file_size > 10 * 1024 * 1024:
                raise ValueError(
                    f"XML part too large: {name}"
                )

            root = ET.fromstring(
                archive.read(member)
            )

            text_boxes += sum(
                1
                for _ in root.iter(
                    f"{w}txbxContent"
                )
            )

            drawings += sum(
                1
                for _ in root.iter(
                    f"{w}drawing"
                )
            )

    if text_boxes:
        warnings.append(
            f"Contains {text_boxes} text box(es); "
            "paragraph traversal may miss their text."
        )

    if drawings:
        warnings.append(
            f"Contains {drawings} drawing(s); "
            "visually inspect images and shapes."
        )

    return warnings


def inspect_template(
    template_path: str | Path,
) -> TemplateReport:

    path = Path(template_path)

    if not path.is_file():
        raise FileNotFoundError(path)

    if path.suffix.lower() != ".docx":
        raise ValueError(
            "This inspector currently accepts .docx only"
        )

    if path.stat().st_size > 25 * 1024 * 1024:
        raise ValueError(
            "DOCX exceeds the 25 MB upload limit"
        )

    warnings = _package_warnings(path)

    document = Document(path)

    blocks: list[TemplateBlock] = []

    # Inspect main body.
    _walk(document, "body", blocks)

    # Inspect headers and footers.
    for index, section in enumerate(document.sections):
        _walk(
            section.header,
            f"header{index}",
            blocks,
        )

        _walk(
            section.footer,
            f"footer{index}",
            blocks,
        )

    # Detect likely resume sections.
    section_hints = []

    for block in blocks:
        if not block.block_id.startswith("body/"):
            continue

        normalized = re.sub(
            r"\s+",
            " ",
            block.text.casefold(),
        ).strip(" :—–-")

        for section_name, aliases in SECTION_NAMES.items():
            if normalized in aliases:
                section_hints.append(
                    SectionHint(
                        section=section_name,
                        block_id=block.block_id,
                        original_heading=block.text,
                    )
                )
                break

    if not section_hints:
        warnings.append(
            "No standard section headings recognized; "
            "mapping requires review."
        )

    if any(
        "/r" in block.block_id
        for block in blocks
    ):
        warnings.append(
            "Template uses tables; "
            "cell-by-cell mapping will be required."
        )

    if any(
        _layout(section).columns > 1
        for section in document.sections
    ):
        warnings.append(
            "Multi-column page sections need "
            "visual mapping before replacement."
        )

    return TemplateReport(
        filename=path.name,
        sha256=hashlib.sha256(
            path.read_bytes()
        ).hexdigest(),
        blocks=blocks,
        section_hints=section_hints,
        layouts=[
            _layout(section)
            for section in document.sections
        ],
        warnings=warnings,
    )
