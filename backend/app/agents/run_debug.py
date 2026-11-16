
import hashlib
import json

from pathlib import Path

from backend.app.agents.graph import graph
from backend.app.services.profile_store import (
    load_profile,
    PROFILE_PATH,
)


inputs = {
    "job_description": """
    Hiring a Junior Full-Stack AI Engineer.
    Required: Flutter, Python, RAG and REST APIs.
    """,
    "target_role": "hybrid",
    "max_pages": 2,
}

profile = load_profile()

fact_lookup = {
    fact.id: {
        "project": work.name,
        "description": fact.description,
    }
    for work in profile.work_items
    for fact in work.facts
}

latest_draft = ""
feedback_history = []
quality_passed = False

# Keep a local copy of the workflow's updates.
last_state = dict(inputs)

for update in graph.stream(
    inputs,
    stream_mode="updates",
):
    for node, data in update.items():
        print(f"\nExecuting: {node}")

        last_state.update(data)

        if node == "profile_retriever":
            print("\n--- SELECTED CAREER FACTS ---")

            for index, fact_id in enumerate(
                data["selected_fact_ids"], 1
            ):
                fact = fact_lookup.get(fact_id)

                if fact:
                    print(
                        f"{index}. [{fact_id}] "
                        f"{fact['project']}"
                    )
                    print(f"   {fact['description']}")
                else:
                    print(f"{index}. {fact_id} - NOT FOUND")

        elif node == "resume_writer":
            latest_draft = data["resume_draft"]

            print(
                "Revision count:",
                data["revision_count"]
            )
            print(
                "Structured document:",
                isinstance(
                    data.get("resume_document"),
                    dict,
                )
            )

        elif node == "resume_evaluator":
            quality_passed = data["quality_passed"]

            feedback = data["evaluation_feedback"]
            feedback_history.append(feedback)

            print("Quality passed:", quality_passed)
            print("Feedback:", feedback)

print("\n--- EVALUATION HISTORY ---")

for index, feedback in enumerate(
    feedback_history, 1
):
    print(f"{index}. {feedback}")

print(
    "\nFINAL STATUS:",
    "PASSED" if quality_passed else "NEEDS REVIEW"
)

print("\nFINAL CV:\n", latest_draft)


# Save reusable structured output without
# triggering another LLM call.
if isinstance(
    last_state.get("resume_document"),
    dict,
):
    snapshot = {
        "resume_document": last_state["resume_document"],
        "selected_fact_ids": last_state[
            "selected_fact_ids"
        ],
        "quality_passed": quality_passed,
        "evaluation_feedback": last_state.get(
            "evaluation_feedback", ""
        ),
        "profile_sha256": hashlib.sha256(
            PROFILE_PATH.read_bytes()
        ).hexdigest(),
    }

    snapshot_path = Path(
        ".cache/resume_pipeline/last_resume_run.json"
    )

    snapshot_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    snapshot_path.write_text(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nSaved snapshot:", snapshot_path)
else:
    print(
        "\nNo structured resume to save. "
        "Check resume_writer.py and state.py."
    )
