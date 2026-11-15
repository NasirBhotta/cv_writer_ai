
from langgraph.graph import StateGraph, START, END

from backend.app.agents.state import ResumeAgentState
from backend.app.agents.jd_analyzer import analyze_job, JobAnalysis
from backend.app.models.profile import (
    MasterProfile, WorkItem, CareerFact
)
from backend.app.services.profile_retriever import retrieve_facts


# Temporary sample profile (database later)
profile = MasterProfile(
    name="Nasir Shahzad",
    work_items=[
        WorkItem(
            id="brainbee",
            name="BrainBee",
            category="project",
            description="AI-powered learning platform",
            technologies=["Flutter", "Node.js", "FAISS"],
            facts=[
                CareerFact(
                    id="brainbee_rag",
                    description="Built a RAG-based chatbot",
                    skills=["RAG", "LLM"]
                ),
                CareerFact(
                    id="brainbee_flutter",
                    description="Developed Flutter mobile application",
                    skills=["Flutter", "Dart"]
                ),
            ]
        )
    ]
)


def prepare_input(state: ResumeAgentState):
    jd = state["job_description"].strip()

    if not jd:
        raise ValueError("Job description cannot be empty")

    return {"job_description": jd}


def initialize_run(state: ResumeAgentState):
    return {
        "revision_count": 0,
        "selected_fact_ids": [],
        "quality_passed": False,
    }


def jd_analyzer_node(state: ResumeAgentState):
    analysis = analyze_job(state["job_description"])
    return {"job_analysis": analysis.model_dump()}


def profile_retriever_node(state: ResumeAgentState):
    analysis = JobAnalysis.model_validate(
        state["job_analysis"]
    )

    fact_ids = retrieve_facts(profile, analysis)

    return {"selected_fact_ids": fact_ids}


builder = StateGraph(ResumeAgentState)

builder.add_node("prepare_input", prepare_input)
builder.add_node("initialize_run", initialize_run)
builder.add_node("jd_analyzer", jd_analyzer_node)
builder.add_node("profile_retriever", profile_retriever_node)

builder.add_edge(START, "prepare_input")
builder.add_edge("prepare_input", "initialize_run")
builder.add_edge("initialize_run", "jd_analyzer")
builder.add_edge("jd_analyzer", "profile_retriever")
builder.add_edge("profile_retriever", END)

graph = builder.compile()


if __name__ == "__main__":
    result = graph.invoke({
        "job_description": """
        Hiring a Junior AI and Flutter Engineer.
        Flutter and RAG experience required.
        """,
        "target_role": "hybrid",
        "max_pages": 2,
    })

    print("Job Analysis:", result["job_analysis"])
    print("Selected Facts:", result["selected_fact_ids"])
