
"""Safe, snapshot-based resume assembly contracts.

This model does not claim multi-user graph generation support.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from backend.app.models.page_layout_policy import (
    PageRequirements,
)


class InsertionChoice(BaseModel):
    work_ids: list[str] = Field(min_length=1)

    experience_anchor: str = Field(min_length=1)
    project_anchor: str = Field(min_length=1)

    experience_style_from: str = Field(min_length=1)
    project_style_from: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(self.work_ids) != len(set(self.work_ids)):
            raise ValueError("Duplicate insertion work IDs.")
        return self


class RemovalChoice(BaseModel):
    titles: list[str] = Field(min_length=1)
    section_start: str = Field(min_length=1)
    section_end: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_titles(self):
        if len(self.titles) != len(set(self.titles)):
            raise ValueError("Duplicate removal titles.")
        return self


class ResumeAssemblyRequest(BaseModel):
    template_path: Path
    approved_snapshot_path: Path
    profile_path: Path

    output_root: Path = Path("outputs/resume_builds")

    job_description: str | None = None

    pages: PageRequirements = Field(
        default_factory=PageRequirements
    )

    converter: Literal[
        "auto",
        "word",
        "libreoffice",
    ] = "auto"

    insertion: InsertionChoice | None = None
    removal: RemovalChoice | None = None

    render_images: bool = True


class ResumePipelineResult(BaseModel):
    run_id: str
    run_directory: str

    status: Literal[
        "failed",
        "needs_review",
    ] = "failed"

    stopped_at: str = "preflight"

    artifacts: dict[str, str] = Field(
        default_factory=dict
    )

    sha256: dict[str, str] = Field(
        default_factory=dict
    )

    content_automated_passed: bool = False
    layout_automated_passed: bool = False
    automated_checks_passed: bool = False

    unresolved_work_ids: list[str] = Field(
        default_factory=list
    )

    retained_template_entries: list[str] = Field(
        default_factory=list
    )

    omitted_selected_fact_ids: list[str] = Field(
        default_factory=list
    )

    review_reasons: list[str] = Field(
        default_factory=list
    )

    warnings: list[str] = Field(
        default_factory=list
    )

    errors: list[str] = Field(
        default_factory=list
    )

    # Human review is not yet integrated.
    # No automated stage may set this to True.
    ready_for_export: Literal[False] = False
