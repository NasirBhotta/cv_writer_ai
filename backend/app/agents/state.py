
from typing import TypedDict, NotRequired, Literal, Any


class ResumeAgentState(TypedDict):
    # Inputs
    job_description: str
    target_role: Literal["flutter", "ai", "hybrid"]
    max_pages: int

    # Job analysis and profile retrieval
    job_analysis: NotRequired[dict[str, Any]]
    selected_fact_ids: NotRequired[list[str]]

    # Resume generation
    resume_document: NotRequired[dict[str, Any]]
    resume_draft: NotRequired[str]

    # Agentic evaluation loop
    evaluation_feedback: NotRequired[str]
    quality_passed: NotRequired[bool]
    revision_count: NotRequired[int]

    # Output & approval (future workflow)
    pdf_path: NotRequired[str]
    approved: NotRequired[bool]
