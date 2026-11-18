
"""Measure rendered DOCX pagination without modifying its content/style.

Requires PyMuPDF for PDF measurement and page PNGs.
A PDF may be exported with installed MS Word (Windows) or LibreOffice.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from docx import Document

from backend.app.models.page_layout_policy import (
    LayoutQAReport,
    PageDecision,
    PageRequirements,
)


def resolve_page_policy(
    requirements: PageRequirements,
    *,
    template_pages: int | None = None,
) -> PageDecision:
    """Resolve strict constraints; treat template length as a soft preference."""
    if template_pages is not None and template_pages < 1:
        raise ValueError("template_pages must be positive.")

    exacts = [
        x for x in (
            requirements.user_exact_pages,
            requirements.employer_exact_pages,
        )
        if x is not None
    ]

    maxima = [
        x for x in (
            requirements.user_max_pages,
            requirements.employer_max_pages,
        )
        if x is not None
    ]

    conflicts: list[str] = []

    if len(set(exacts)) > 1:
        conflicts.append(
            "User and employer specify different exact page counts."
        )

    exact = exacts[0] if exacts else None
    maximum = min(maxima) if maxima else None

    if (
        exact is not None
        and maximum is not None
        and exact > maximum
    ):
        conflicts.append(
            f"Exact requirement ({exact}) exceeds "
            f"strict maximum ({maximum})."
        )

    mode = (
        "exact"
        if exact is not None
        else "maximum"
        if maximum is not None
        else "template_preference"
        if template_pages is not None
        else "unrestricted"
    )

    return PageDecision(
        mode=mode,
        exact_pages=exact,
        maximum_pages=maximum,
        preferred_pages=template_pages,
        conflicts=conflicts,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def _pdf_info(path: Path) -> tuple[int, list[int]]:
    """Count rendered PDF pages, not DOCX metadata pages."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PDF QA requires: uv add pymupdf"
        ) from exc

    with fitz.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError(
                "Encrypted PDF cannot be audited."
            )

        if not pdf.is_pdf or len(pdf) < 1:
            raise ValueError(
                "No valid PDF pages found."
            )

        return (
            len(pdf),
            [
                len(page.get_text().strip())
                for page in pdf
            ],
        )


def _word_export(
    source: Path,
    destination: Path,
) -> None:
    """Windows Word COM export; read-only with macros disabled."""

    def ps_quote(value: Path) -> str:
        return "'" + str(value).replace(
            "'", "''"
        ) + "'"

    script = f"""
$ErrorActionPreference = 'Stop'
$word = $null
$doc = $null
try {{
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3
    $doc = $word.Documents.Open({ps_quote(source)}, $false, $true)
    $doc.ExportAsFixedFormat({ps_quote(destination)}, 17)
}} finally {{
    if ($null -ne $doc) {{ $doc.Close($false) }}
    if ($null -ne $word) {{ $word.Quit() }}
}}
"""

    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _libreoffice_export(
    source: Path,
    destination: Path,
) -> None:
    binary = (
        shutil.which("soffice")
        or shutil.which("libreoffice")
    )

    if binary is None and os.name == "nt":
        candidate = Path(
            r"C:\Program Files\LibreOffice\program\soffice.exe"
        )

        if candidate.is_file():
            binary = str(candidate)

    if binary is None:
        raise RuntimeError(
            "LibreOffice executable not found."
        )

    subprocess.run(
        [
            binary,
            "--headless",
            "--convert-to",
            "pdf:writer_pdf_Export",
            "--outdir",
            str(destination.parent),
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )

    produced = (
        destination.parent
        / f"{source.stem}.pdf"
    )

    if produced != destination:
        if not produced.is_file():
            raise RuntimeError(
                "LibreOffice did not produce a PDF."
            )

        produced.rename(destination)


def export_docx_to_pdf(
    source_path: str | Path,
    output_path: str | Path,
    *,
    engine: str = "auto",
) -> Path:
    """Create a new PDF; never overwrite an existing output or DOCX."""

    source = Path(source_path).resolve()
    output = Path(output_path).resolve()

    if (
        not source.is_file()
        or source.suffix.lower() != ".docx"
    ):
        raise ValueError(
            f"Not a DOCX file: {source}"
        )

    if (
        output.suffix.lower() != ".pdf"
        or source == output
    ):
        raise ValueError(
            "Output must be a distinct .pdf path."
        )

    if output.exists():
        raise FileExistsError(output)

    if engine not in {
        "auto", "word", "libreoffice"
    }:
        raise ValueError(
            "engine must be auto, word, or libreoffice."
        )

    source_hash = _sha256(source)
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    engines = (
        ["word", "libreoffice"]
        if os.name == "nt"
        else ["libreoffice"]
    )

    if engine != "auto":
        engines = [engine]

    failures = []

    with tempfile.TemporaryDirectory(
        prefix="cv-layout-"
    ) as tmp:

        for name in engines:
            temporary_pdf = (
                Path(tmp) / "converted.pdf"
            )

            temporary_pdf.unlink(
                missing_ok=True
            )

            try:
                if name == "word":
                    if os.name != "nt":
                        raise RuntimeError(
                            "Word COM only works on Windows."
                        )

                    _word_export(
                        source,
                        temporary_pdf,
                    )

                else:
                    _libreoffice_export(
                        source,
                        temporary_pdf,
                    )

                if not temporary_pdf.is_file():
                    raise RuntimeError(
                        "Converter returned without "
                        "creating PDF."
                    )

                _pdf_info(temporary_pdf)

                if _sha256(source) != source_hash:
                    raise RuntimeError(
                        "Source DOCX changed during conversion."
                    )

                # Exclusive creation: no silent overwrites.
                with (
                    output.open("xb") as target,
                    temporary_pdf.open("rb") as content,
                ):
                    shutil.copyfileobj(
                        content,
                        target,
                    )

                return output

            except FileExistsError:
                raise

            except (
                OSError,
                RuntimeError,
                ValueError,
                subprocess.SubprocessError,
            ) as exc:
                failures.append(
                    f"{name}: {type(exc).__name__}: {exc}"
                )

    raise RuntimeError(
        "No PDF converter succeeded. "
        + " | ".join(failures)
    )


def audit_resume_layout(
    *,
    source_docx: str | Path,
    pdf_path: str | Path,
    requirements: PageRequirements,
    template_pdf_path: str | Path | None = None,
    render_dir: str | Path | None = None,
    pdf_generated_from_source_this_run: bool = False,
) -> LayoutQAReport:
    """Read PDF; optionally produce page PNGs for human inspection."""

    source = Path(source_docx)
    pdf_file = Path(pdf_path)

    if (
        not source.is_file()
        or not pdf_file.is_file()
    ):
        raise FileNotFoundError(
            "DOCX and its rendered PDF must both exist."
        )

    source_hash = _sha256(source)
    pdf_hash = _sha256(pdf_file)

    document = Document(source)

    # These are explicit Word break instructions,
    # NOT the actual number of rendered pages.
    page_breaks = [
        i
        for i, paragraph in enumerate(
            document.paragraphs
        )
        if paragraph._p.xpath(
            './/w:br[@w:type="page"]'
        )
    ]

    before_breaks = [
        i
        for i, paragraph in enumerate(
            document.paragraphs
        )
        if paragraph._p.xpath(
            ".//w:pageBreakBefore"
        )
    ]

    actual, characters = _pdf_info(
        pdf_file
    )

    template_pages = None

    if template_pdf_path is not None:
        template_pages, _ = _pdf_info(
            Path(template_pdf_path)
        )

    decision = resolve_page_policy(
        requirements,
        template_pages=template_pages,
    )

    errors = list(decision.conflicts)
    warnings = []

    if not pdf_generated_from_source_this_run:
        warnings.append(
            "Provided PDF was not generated from this "
            "DOCX in the current run; verify that "
            "the files correspond."
        )

    if (
        decision.exact_pages is not None
        and actual != decision.exact_pages
    ):
        errors.append(
            f"Actual {actual} pages != required "
            f"exactly {decision.exact_pages}."
        )

    if (
        decision.maximum_pages is not None
        and actual > decision.maximum_pages
    ):
        errors.append(
            f"Actual {actual} pages exceeds "
            f"maximum {decision.maximum_pages}."
        )

    if (
        decision.exact_pages is None
        and template_pages is not None
        and actual != template_pages
    ):
        warnings.append(
            f"Template preference is {template_pages} "
            f"pages; output is {actual}. Review "
            "relevance and natural reflow; "
            "do not force page count."
        )

    if page_breaks or before_breaks:
        warnings.append(
            "Manual page breaks present: review "
            "whether they still make sense "
            "after adding/removing entries."
        )

    if any(
        count == 0
        for count in characters
    ):
        warnings.append(
            "At least one PDF page has no "
            "extractable text; inspect images."
        )

    images: list[str] = []

    if render_dir is not None:
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError(
                "Rendering requires: uv add pymupdf"
            ) from exc

        folder = Path(render_dir)
        folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        targets = [
            folder / f"page-{i + 1}.png"
            for i in range(actual)
        ]

        if any(
            path.exists()
            for path in targets
        ):
            raise FileExistsError(
                "Render directory already "
                "contains page images."
            )

        with fitz.open(pdf_file) as pdf:
            for i, page in enumerate(pdf):
                page.get_pixmap(
                    matrix=fitz.Matrix(1.5, 1.5),
                    alpha=False,
                ).save(
                    str(targets[i])
                )

                images.append(
                    str(targets[i])
                )

    if (
        _sha256(source) != source_hash
        or _sha256(pdf_file) != pdf_hash
    ):
        raise RuntimeError(
            "Document changed during "
            "read-only layout QA."
        )

    return LayoutQAReport(
        source_docx=str(source),
        source_sha256=source_hash,
        pdf_path=str(pdf_file),
        pdf_sha256=pdf_hash,
        template_pdf_path=(
            str(template_pdf_path)
            if template_pdf_path
            else None
        ),
        template_pages=template_pages,
        actual_pages=actual,
        page_text_characters=characters,
        manual_page_break_paragraphs=page_breaks,
        page_break_before_paragraphs=before_breaks,
        decision=decision,
        page_images=images,
        pdf_generated_from_source_this_run=(
            pdf_generated_from_source_this_run
        ),
        warnings=warnings,
        errors=errors,
        automated_checks_passed=not errors,
    )
