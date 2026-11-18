
import hashlib
import json

from pathlib import Path

from backend.app.agents.graph import graph
from backend.app.services.profile_store import (
    load_profile,
    PROFILE_PATH,
)


SNAPSHOT_DIR = Path(".cache/resume_pipeline")


def save_snapshot(
    state: dict,
    *,
    completed: bool,
    error: str | None = None,
) -> Path | None:
    """
    Save the most recent structured resume.

    Completed workflow:
        last_resume_run.json

    Interrupted workflow:
        failed_resume_run.json

    Never overwrite a previous completed run
    with an interrupted run.
    """

    document = state.get("resume_document")
    fact_ids = state.get("selected_fact_ids")

    if not isinstance(document, dict):
        print(
            "\nNo structured resume available to save."
        )
        return None

    if not isinstance(fact_ids, list) or not fact_ids:
        print(
            "\nNo selected career facts available."
        )
        return None

    snapshot = {
        "resume_document": document,
        "selected_fact_ids": fact_ids,
        "quality_passed": bool(
            state.get("quality_passed", False)
        ),
        "evaluation_feedback": state.get(
            "evaluation_feedback",
            "",
        ),
        "profile_sha256": hashlib.sha256(
            PROFILE_PATH.read_bytes()
        ).hexdigest(),
        "run_status": (
            "completed"
            if completed
            else "interrupted"
        ),
        "error": error,
        "revision_count": state.get(
            "revision_count",
            0,
        ),
    }

    SNAPSHOT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    filename = (
        "last_resume_run.json"
        if completed
        else "failed_resume_run.json"
    )

    destination = SNAPSHOT_DIR / filename

    temporary = destination.with_suffix(
        ".json.tmp"
    )

    temporary.write_text(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    temporary.replace(destination)

    print("\nSaved snapshot:", destination)

    return destination


def main() -> None:
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

    last_state = dict(inputs)

    feedback_history = []
    completed = False
    error_message = None

    try:
        for update in graph.stream(
            inputs,
            stream_mode="updates",
        ):
            for node, data in update.items():
                print(f"\nExecuting: {node}")

                last_state.update(data)

                if node == "profile_retriever":
                    print(
                        "\n--- SELECTED CAREER FACTS ---"
                    )

                    for index, fact_id in enumerate(
                        data["selected_fact_ids"],
                        1,
                    ):
                        fact = fact_lookup.get(
                            fact_id
                        )

                        if fact:
                            print(
                                f"{index}. [{fact_id}] "
                                f"{fact['project']}"
                            )
                            print(
                                f"   {fact['description']}"
                            )
                        else:
                            print(
                                f"{index}. {fact_id} "
                                "- NOT FOUND"
                            )

                elif node == "resume_writer":
                    print(
                        "Revision count:",
                        data.get("revision_count"),
                    )

                    print(
                        "Structured document:",
                        isinstance(
                            data.get("resume_document"),
                            dict,
                        ),
                    )

                elif node == "resume_evaluator":
                    feedback = data.get(
                        "evaluation_feedback",
                        "",
                    )

                    feedback_history.append(
                        feedback
                    )

                    print(
                        "Quality passed:",
                        data.get(
                            "quality_passed",
                            False,
                        ),
                    )

                    print(
                        "Feedback:",
                        feedback,
                    )

        completed = True

    except Exception as exc:
        error_message = (
            f"{type(exc).__name__}: {exc}"
        )

        print(
            "\nGRAPH INTERRUPTED:",
            error_message,
        )

        raise

    finally:
        # This executes even when a request times out.
        save_snapshot(
            last_state,
            completed=completed,
            error=error_message,
        )

        print(
            "\n--- EVALUATION HISTORY ---"
        )

        for index, feedback in enumerate(
            feedback_history,
            1,
        ):
            print(
                f"{index}. {feedback}"
            )

        print(
            "\nFINAL STATUS:",
            (
                "PASSED"
                if completed
                and last_state.get(
                    "quality_passed",
                    False,
                )
                else "NEEDS REVIEW"
            ),
        )

        draft = last_state.get(
            "resume_draft",
            "",
        )

        if draft:
            print(
                "\nLATEST AVAILABLE CV:\n",
                draft,
            )


if __name__ == "__main__":
    main()
