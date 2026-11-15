
from langgraph.graph import StateGraph, START, END
from backend.app.agents.state import ResumeAgentState


# Node 1: Prepare job description
def prepare_input(state: ResumeAgentState):
    jd = state["job_description"].strip()

    if not jd:
        raise ValueError("Job description cannot be empty")

    return {"job_description": jd}


# Node 2: Initialize workflow
def initialize_run(state: ResumeAgentState):
    return {
        "revision_count": 0,
        "selected_fact_ids": [],
        "quality_passed": False,
    }


# Build graph
builder = StateGraph(ResumeAgentState)

builder.add_node("prepare_input", prepare_input)
builder.add_node("initialize_run", initialize_run)

builder.add_edge(START, "prepare_input")
builder.add_edge("prepare_input", "initialize_run")
builder.add_edge("initialize_run", END)

graph = builder.compile()


if __name__ == "__main__":
    result = graph.invoke({
        "job_description": "  Hiring Flutter and AI Engineer  ",
        "target_role": "hybrid",
        "max_pages": 2,
    })

    print(result)
