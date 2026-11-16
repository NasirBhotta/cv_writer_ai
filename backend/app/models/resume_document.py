
from typing import Literal

from pydantic import BaseModel, Field


class ResumeBullet(BaseModel):
    fact_id: str = Field(min_length=1)
    text: str = Field(min_length=10)


class ResumeEntry(BaseModel):
    work_id: str = Field(min_length=1)
    section: Literal["experience", "project"]
    bullets: list[ResumeBullet] = Field(min_length=1)


class SkillGroup(BaseModel):
    title: str = Field(min_length=1)
    skills: list[str] = Field(min_length=1)


class ResumeDocument(BaseModel):
    headline: str = Field(min_length=3)
    summary: str = Field(min_length=40)
    skill_groups: list[SkillGroup] = Field(min_length=1)
    entries: list[ResumeEntry] = Field(min_length=1)
