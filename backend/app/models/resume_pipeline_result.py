
"""Contracts shared by snapshot assembly and fresh-JD generation."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.models.page_layout_policy import PageRequirements


class InsertionChoice(BaseModel):
    work_ids: list[str] = Field(min_length=1)
    experience_anchor: str = Field(min_length=1)
    project_anchor: str = Field(min_length=1)
    experience_style_from: str = Field(min_length=1)
    project_style_from: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_work_ids(self):
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


class ContinuationHeaderChoice(BaseModel):
    """User-approved exact anchors; no automatic header deletion."""

    identity: str = Field(min_length=1)
    repeated_heading: str = Field(min_length=1)
    repeated_links: str = Field(min_length=1)
    next_section: str = Field(min_length=1)


class ResumeAssemblyRequest(BaseModel):
    template_path: Path
    approved_snapshot_path: Path
    profile_path: Path
    output_root: Path = Path("outputs/resume_builds")
    job_description: str | None = None
    pages: PageRequirements = Field(default_factory=PageRequirements)
    converter: Literal["auto", "word", "libreoffice"] = "auto"
    insertion: InsertionChoice | None = None
    removal: RemovalChoice | None = None
    continuation_header: ContinuationHeaderChoice | None = None
    render_images: bool = True


class FreshResumeRequest(BaseModel):
    """Single-user mode, using the existing repository master profile."""

    template_path: Path
    job_description: str = Field(min_length=20)
    output_root: Path = Path("outputs/fresh_resume_runs")
    target_role: Literal["flutter", "ai", "hybrid"] = "hybrid"
    max_pages: int = Field(ge=1, le=20)
    converter: Literal["auto", "word", "libreoffice"] = "auto"
    insertion: InsertionChoice | None = None
    removal: RemovalChoice | None = None
    continuation_header: ContinuationHeaderChoice | None = None
    render_images: bool = True

    @field_validator("job_description")
    @classmethod
    def normalize_job_description(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 20:
            raise ValueError("Job description needs at least 20 characters.")
        return value


class ResumePipelineResult(BaseModel):
    run_id: str
    run_directory: str
    status: Literal["failed", "rejected", "needs_review"] = "failed"
    stopped_at: str = "preflight"
    artifacts: dict[str, str] = Field(default_factory=dict)
    sha256: dict[str, str] = Field(default_factory=dict)
    graph_quality_passed: bool = False
    semantic_history: list[dict] = Field(default_factory=list)
    semantic_passed: bool = False
    content_automated_passed: bool = False
    layout_automated_passed: bool = False
    automated_checks_passed: bool = False
    unresolved_work_ids: list[str] = Field(default_factory=list)
    retained_template_entries: list[str] = Field(default_factory=list)
    omitted_selected_fact_ids: list[str] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    ready_for_export: Literal[False] = False
