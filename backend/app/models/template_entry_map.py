
from typing import Literal

from pydantic import BaseModel, Field

from backend.app.models.template_edit_plan import TemplateEditPlan


class TemplateEntrySlot(BaseModel):
    section: Literal["experience", "projects"]
    heading_block_id: str
    heading_text: str
    bullet_block_ids: list[str]
    work_id: str | None = None
    needs_review: bool = False


class TemplateEntryMap(BaseModel):
    template_sha256: str
    slots: list[TemplateEntrySlot] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DocumentBridgeResult(BaseModel):
    plan: TemplateEditPlan | None = None
    skipped: list[str] = Field(default_factory=list)
    preview_only: bool = True
