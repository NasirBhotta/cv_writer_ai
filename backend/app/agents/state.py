
from typing import TypedDict, NotRequired, Literal


class ResumeAgentState(TypedDict):
    # Inputs
    job_description: str
    target_role: Literal["flutter", "ai", "hybrid"]
    max_pages: int

    # Profile retrieval
    selected_fact_ids: NotRequired[list[str]]

    # Resume generation
    resume_draft: NotRequired[str]

    # Agentic evaluation loop
    evaluation_feedback: NotRequired[str]
    quality_passed: NotRequired[bool]
    revision_count: NotRequired[int]

    # Output & approval
    pdf_path: NotRequired[str]
    approved: NotRequired[bool]
