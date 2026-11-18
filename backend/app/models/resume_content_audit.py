
"""Read-only content QA report models. No changes to a resume."""

from typing import Literal

from pydantic import BaseModel, Field


class EntryCoverage(BaseModel):
    work_id: str
    section: Literal["experience", "project"]
    matched_heading: str | None = None
    heading_count: int = 0
    expected_bullets: int
    matched_bullets: int = 0
    missing_fact_ids: list[str] = Field(
        default_factory=list
    )
    extra_bullets: list[str] = Field(
        default_factory=list
    )
    status: Literal["pass", "review", "fail"] = "fail"
    notes: list[str] = Field(
        default_factory=list
    )


class OmittedFact(BaseModel):
    work_id: str
    fact_id: str
    source_fact: str
    selected_by_retriever: bool
    jd_term_matches: list[str] = Field(
        default_factory=list
    )
    reason: str


class RetainedTemplateEntry(BaseModel):
    work_id: str
    heading: str
    reason: str = (
        "Present in DOCX but absent from approved "
        "ResumeDocument; review before removal."
    )


class ResumeContentAudit(BaseModel):
    source_path: str
    snapshot_path: str
    source_sha256: str

    approved_work_ids: list[str]
    entries: list[EntryCoverage]

    omitted_selected_facts: list[OmittedFact] = Field(
        default_factory=list
    )

    potentially_relevant_unselected_facts: list[
        OmittedFact
    ] = Field(default_factory=list)

    retained_template_entries: list[
        RetainedTemplateEntry
    ] = Field(default_factory=list)

    jd_terms: list[str] = Field(
        default_factory=list
    )

    jd_relevance_reviewed: bool = False
    approved_content_complete: bool = False

    errors: list[str] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(
        default_factory=list
    )

    read_only: bool = True
    visual_layout_verified: bool = False
    ready_for_final_export: bool = False
