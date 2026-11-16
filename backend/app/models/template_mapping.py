
from typing import Literal

from pydantic import BaseModel, Field


SectionType = Literal[
    "summary",
    "experience",
    "projects",
    "skills",
    "education",
    "languages",
    "certifications",
    "technical_content",
    "featured_work",
    "mixed",
    "unknown",
]


class TemplateRegion(BaseModel):
    section: SectionType
    heading_id: str
    heading_text: str

    possible_sections: list[str] = Field(
        default_factory=list
    )

    content_block_ids: list[str] = Field(
        default_factory=list
    )

    needs_review: bool = False


class TemplateMapping(BaseModel):
    template_sha256: str
    regions: list[TemplateRegion]
    warnings: list[str] = Field(
        default_factory=list
    )
