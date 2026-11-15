
from langgraph.graph import StateGraph, START, END

from backend.app.agents.state import ResumeAgentState
from backend.app.agents.jd_analyzer import analyze_job


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


builder = StateGraph(ResumeAgentState)

builder.add_node("prepare_input", prepare_input)
builder.add_node("initialize_run", initialize_run)
builder.add_node("jd_analyzer", jd_analyzer_node)

builder.add_edge(START, "prepare_input")
builder.add_edge("prepare_input", "initialize_run")
builder.add_edge("initialize_run", "jd_analyzer")
builder.add_edge("jd_analyzer", END)

graph = builder.compile()


if __name__ == "__main__":
    result = graph.invoke({
        "job_description": """
        Hiring a Junior Full-Stack AI Engineer.
        Required: Python, Flutter, Node.js, REST APIs.
        LangGraph and RAG experience preferred.
        """,
        "target_role": "hybrid",
        "max_pages": 2,
    })

    print(result["job_analysis"])
