
import os

from langgraph.graph import StateGraph, START, END

from backend.app.agents.state import ResumeAgentState
from backend.app.agents.jd_analyzer import (
    analyze_job,
    JobAnalysis,
)
from backend.app.agents.resume_writer import (
    resume_writer_node,
)
from backend.app.agents.resume_evaluator import (
    resume_evaluator_node,
)
from backend.app.services.profile_store import load_profile
from backend.app.services.profile_retriever import retrieve_facts


# Default: 3 revisions.
# Development: set RESUME_MAX_REVISIONS=1
MAX_REVISIONS = max(
    0,
    int(os.getenv("RESUME_MAX_REVISIONS", "3")),
)


def prepare_input(state: ResumeAgentState) -> dict:
    job_description = state["job_description"].strip()

    if not job_description:
        raise ValueError("Job description cannot be empty")

    return {
        "job_description": job_description,
    }


def initialize_run(state: ResumeAgentState) -> dict:
    return {
        "revision_count": 0,
        "selected_fact_ids": [],
        "quality_passed": False,
        "evaluation_feedback": "",
        "resume_draft": "",
    }


def jd_analyzer_node(state: ResumeAgentState) -> dict:
    analysis = analyze_job(state["job_description"])

    return {
        "job_analysis": analysis.model_dump(),
    }


def profile_retriever_node(
    state: ResumeAgentState,
) -> dict:
    analysis = JobAnalysis.model_validate(
        state["job_analysis"]
    )

    # Always use the saved master profile.
    profile = load_profile()

    total_facts = sum(
        len(work.facts)
        for work in profile.work_items
    )

    print(
        f"Profile: {len(profile.work_items)} work items, "
        f"{total_facts} facts"
    )

    selected_ids = retrieve_facts(
        profile=profile,
        job=analysis,
        limit=18,
    )

    return {
        "selected_fact_ids": selected_ids,
    }


def route_after_evaluation(
    state: ResumeAgentState,
) -> str:

    if state.get("quality_passed", False):
        return "finish"

    if state.get("revision_count", 0) >= MAX_REVISIONS:
        return "finish"

    return "revise"


builder = StateGraph(ResumeAgentState)

builder.add_node("prepare_input", prepare_input)
builder.add_node("initialize_run", initialize_run)
builder.add_node("jd_analyzer", jd_analyzer_node)
builder.add_node("profile_retriever", profile_retriever_node)
builder.add_node("resume_writer", resume_writer_node)
builder.add_node("resume_evaluator", resume_evaluator_node)

builder.add_edge(START, "prepare_input")
builder.add_edge("prepare_input", "initialize_run")
builder.add_edge("initialize_run", "jd_analyzer")
builder.add_edge("jd_analyzer", "profile_retriever")
builder.add_edge("profile_retriever", "resume_writer")
builder.add_edge("resume_writer", "resume_evaluator")

builder.add_conditional_edges(
    "resume_evaluator",
    route_after_evaluation,
    {
        "revise": "resume_writer",
        "finish": END,
    },
)

graph = builder.compile()


if __name__ == "__main__":
    result = graph.invoke({
        "job_description": """
        Hiring a Junior Full-Stack AI Engineer.
        Required: Flutter, Python, RAG and REST APIs.
        """,
        "target_role": "hybrid",
        "max_pages": 2,
    })

    print("\nSelected Facts:", result["selected_fact_ids"])
    print("Revisions:", result["revision_count"])
    print("Quality Passed:", result["quality_passed"])
    print("Feedback:", result["evaluation_feedback"])
    print("\nGENERATED CV:\n")
    print(result["resume_draft"])
