from typing import Literal

from pydantic import BaseModel, Field


class ParagraphReplacement(BaseModel):
    block_id: str
    section: Literal["summary", "experience", "projects"]
    mode: Literal["plain", "bullet"] = "plain"
    old_text: str
    new_text: str = Field(min_length=1, max_length=1200)


class TemplateEditPlan(BaseModel):
    template_sha256: str
    edits: list[ParagraphReplacement] = Field(default_factory=list)
