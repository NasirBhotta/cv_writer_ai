
from pydantic import BaseModel, Field


class TemplateBlock(BaseModel):
    block_id: str
    text: str
    style_name: str
    alignment: str | None = None
    font_names: list[str] = Field(default_factory=list)
    has_bold_run: bool = False


class SectionHint(BaseModel):
    section: str
    block_id: str
    original_heading: str


class PageLayout(BaseModel):
    page_width_in: float
    page_height_in: float
    top_margin_in: float
    bottom_margin_in: float
    left_margin_in: float
    right_margin_in: float
    columns: int


class TemplateReport(BaseModel):
    filename: str
    sha256: str
    blocks: list[TemplateBlock]
    section_hints: list[SectionHint]
    layouts: list[PageLayout]
    warnings: list[str] = Field(default_factory=list)
