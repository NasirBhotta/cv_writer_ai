
from typing import Any

from pydantic import BaseModel, Field, model_validator

from backend.app.models.resume_document import ResumeDocument


class SavedResumeRun(BaseModel):
    resume_document: ResumeDocument
    selected_fact_ids: list[str] = Field(min_length=1)
    quality_passed: bool
    profile_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    evaluation_feedback: Any = None

    @model_validator(mode="after")
    def reject_duplicate_facts(self):
        if len(self.selected_fact_ids) != len(
            set(self.selected_fact_ids)
        ):
            raise ValueError(
                "Saved run has duplicate selected_fact_ids."
            )

        return self


class SavedPreviewManifest(BaseModel):
    template_path: str
    snapshot_path: str

    template_sha256: str
    profile_sha256: str

    quality_passed: bool
    summary_included: bool

    planned_block_ids: list[str] = Field(
        default_factory=list
    )

    updated_work_ids: list[str] = Field(
        default_factory=list
    )

    skipped_entries: list[str] = Field(
        default_factory=list
    )

    unchanged_template_entries: list[str] = Field(
        default_factory=list
    )

    warnings: list[str] = Field(
        default_factory=list
    )

    preview_only: bool = True
