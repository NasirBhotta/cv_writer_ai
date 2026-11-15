
from backend.app.agents.graph import graph
from backend.app.services.profile_store import load_profile


inputs = {
    "job_description": """
    Hiring a Junior Full-Stack AI Engineer.
    Required: Flutter, Python, RAG and REST APIs.
    """,
    "target_role": "hybrid",
    "max_pages": 2,
}

latest_draft = ""
feedback_history = []
quality_passed = False

# Load profile once
profile = load_profile()

# Map fact IDs to project details
fact_lookup = {
    fact.id: {
        "project": work.name,
        "description": fact.description,
    }
    for work in profile.work_items
    for fact in work.facts
}

for update in graph.stream(inputs, stream_mode="updates"):
    for node, data in update.items():
        print(f"\nExecuting: {node}")

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
                    print(
                        f"   {fact['description']}"
                    )
                else:
                    print(f"{index}. {fact_id} - NOT FOUND")

        elif node == "resume_writer":
            latest_draft = data["resume_draft"]
            print(
                "Revision count:",
                data["revision_count"]
            )

        elif node == "resume_evaluator":
            quality_passed = data["quality_passed"]
            feedback = data["evaluation_feedback"]

            feedback_history.append(feedback)

            print("Quality passed:", quality_passed)
            print("Feedback:", feedback)

print("\n--- EVALUATION HISTORY ---")
for index, feedback in enumerate(feedback_history, 1):
    print(f"{index}. {feedback}")

print(
    "\nFINAL STATUS:",
    "PASSED" if quality_passed else "NEEDS REVIEW"
)

print("\nFINAL CV:\n", latest_draft)
