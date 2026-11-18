
"""Page-count requirements and machine-verifiable layout QA results."""

from typing import Literal

from pydantic import BaseModel, Field


class PageRequirements(BaseModel):
    # Explicit constraints, not guesses based on JD length.
    user_exact_pages: int | None = Field(default=None, ge=1)
    user_max_pages: int | None = Field(default=None, ge=1)

    employer_exact_pages: int | None = Field(
        default=None,
        ge=1,
    )
    employer_max_pages: int | None = Field(
        default=None,
        ge=1,
    )


class PageDecision(BaseModel):
    mode: Literal[
        "exact",
        "maximum",
        "template_preference",
        "unrestricted",
    ]

    exact_pages: int | None = None
    maximum_pages: int | None = None
    preferred_pages: int | None = None

    conflicts: list[str] = Field(default_factory=list)


class LayoutQAReport(BaseModel):
    source_docx: str
    source_sha256: str

    pdf_path: str
    pdf_sha256: str

    template_pdf_path: str | None = None
    template_pages: int | None = None

    actual_pages: int
    page_text_characters: list[int]

    manual_page_break_paragraphs: list[int]
    page_break_before_paragraphs: list[int]

    decision: PageDecision

    page_images: list[str] = Field(default_factory=list)
    pdf_generated_from_source_this_run: bool = False

    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    automated_checks_passed: bool = False
    visual_review_pending: bool = True
    ready_for_final_export: bool = False
