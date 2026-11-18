
"""Read-only audit models for DOCX entry removal."""

from pydantic import BaseModel, Field


class RemovalTarget(BaseModel):
    title: str
    heading_index: int

    bullet_indices: list[int] = Field(
        default_factory=list
    )

    safe: bool
    reason: str = ""


class EntryRemovalPlan(BaseModel):
    source_path: str
    source_sha256: str

    section_start: str
    section_end: str

    targets: list[RemovalTarget] = Field(
        default_factory=list
    )

    warnings: list[str] = Field(
        default_factory=list
    )

    preview_only: bool = True

    @property
    def can_apply(self) -> bool:
        return (
            bool(self.targets)
            and all(
                target.safe
                for target in self.targets
            )
        )
