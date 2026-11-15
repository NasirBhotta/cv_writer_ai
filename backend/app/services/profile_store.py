
from pathlib import Path

from backend.app.models.profile import (
    MasterProfile,
    WorkItem,
    CareerFact,
)


PROFILE_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "master_profile.json"
)


def save_profile(profile: MasterProfile) -> None:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(
        profile.model_dump_json(indent=2),
        encoding="utf-8",
    )


def load_profile() -> MasterProfile:
    if not PROFILE_PATH.exists():
        raise FileNotFoundError("Master profile not found")

    return MasterProfile.model_validate_json(
        PROFILE_PATH.read_text(encoding="utf-8")
    )


def make_fact(id: str, description: str, skills: list[str]):
    return CareerFact(
        id=id,
        description=description,
        skills=skills,
    )


def get_career_data() -> list[WorkItem]:
    return [
        WorkItem(
            id="brainbee",
            name="BrainBee",
            category="project",
            description="AI-powered learning platform for grades 5–12.",
            technologies=[
                "Flutter", "Dart", "Node.js",
                "Express.js", "MongoDB", "Gemini",
                "FAISS", "Socket.IO"
            ],
            facts=[
                make_fact(
                    "brainbee_rag",
                    "Built an educational RAG chatbot using Gemini and FAISS.",
                    ["RAG", "LLM", "Gemini", "FAISS"]
                ),
                make_fact(
                    "brainbee_flutter",
                    "Developed the Flutter student application.",
                    ["Flutter", "Dart"]
                ),
                make_fact(
                    "brainbee_quizzes",
                    "Implemented AI-powered quiz and flashcard generation.",
                    ["LLM", "Gemini", "Node.js"]
                ),
                make_fact(
                    "brainbee_battle",
                    "Implemented peer battle functionality using Socket.IO.",
                    ["Socket.IO", "Node.js"]
                ),
                make_fact(
                    "brainbee_users",
                    "Reported 3,000+ users of the learning platform.",
                    ["Product Development"]
                ),
            ],
        ),

        WorkItem(
            id="nizaam",
            name="NIZAAM",
            category="project",
            description="Mobile shop management SaaS.",
            technologies=[
                "Flutter", "Dart", "Node.js",
                "Express.js", "MongoDB", "Firebase"
            ],
            facts=[
                make_fact(
                    "nizaam_management",
                    "Built sales, inventory and repair management features.",
                    ["Flutter", "Node.js", "MongoDB"]
                ),
                make_fact(
                    "nizaam_offline",
                    "Implemented offline desktop functionality.",
                    ["Flutter", "Offline Storage"]
                ),
                make_fact(
                    "nizaam_shops",
                    "Reported serving more than 100 shops.",
                    ["SaaS", "Product Development"]
                ),
            ],
        ),

        WorkItem(
            id="uniproof",
            name="UniProof AI",
            category="project",
            description="Multi-agent university research system (in development).",
            technologies=[
                "Python", "AI Agents", "LLMs"
            ],
            facts=[
                make_fact(
                    "uniproof_agents",
                    "Developing agents for document analysis and university eligibility evaluation.",
                    ["Python", "AI Agents", "LLM"]
                ),
                make_fact(
                    "uniproof_ranking",
                    "Developing program ranking and university shortlisting workflows.",
                    ["AI Agents", "Automation"]
                ),
            ],
        ),

        WorkItem(
            id="axaon_24ifix",
            name="24iFix",
            category="internship",
            description="Flutter mobile application for Apple device repair bookings at AXAON Software.",
            technologies=[
                "Flutter", "Dart", "GoRouter"
            ],
            facts=[
                make_fact(
                    "24ifix_ui",
                    "Implemented splash, onboarding and authentication interfaces.",
                    ["Flutter", "Dart"]
                ),
                make_fact(
                    "24ifix_navigation",
                    "Configured application navigation using GoRouter.",
                    ["Flutter", "GoRouter"]
                ),
            ],
        ),

        WorkItem(
            id="glowsims_lms",
            name="LMS & TALIB",
            category="internship",
            description="Learning management and teacher-student application work at GlowSims.",
            technologies=[
                "Flutter", "Node.js", "Backend APIs"
            ],
            facts=[
                make_fact(
                    "lms_latency",
                    "Reduced reported LMS backend p95 latency from 1100ms to 420ms.",
                    ["Node.js", "Backend Optimization"]
                ),
                make_fact(
                    "talib_performance",
                    "Reduced reported TALIB dashboard loading time from 3.2s to 1.4s.",
                    ["Flutter", "Performance Optimization"]
                ),
            ],
        ),

        WorkItem(
            id="crifly_apps",
            name="Shoutsy & GotCakey",
            category="job",
            description="Team-based Flutter application development at Crifly.",
            technologies=["Flutter", "Dart", "Figma"],
            facts=[
                make_fact(
                    "crifly_figma",
                    "Converted Figma designs into Flutter application interfaces as part of a development team.",
                    ["Flutter", "Dart", "Figma"]
                ),
            ],
        ),

        WorkItem(
            id="ecommerce",
            name="Flutter E-Commerce",
            category="project",
            description="Flutter e-commerce application with Firebase and Stripe.",
            technologies=[
                "Flutter", "Firebase", "Stripe", "FCM"
            ],
            facts=[
                make_fact(
                    "ecommerce_payments",
                    "Integrated Stripe payment functionality.",
                    ["Flutter", "Stripe"]
                ),
                make_fact(
                    "ecommerce_firebase",
                    "Implemented Firebase-backed application features and push notifications.",
                    ["Firebase", "FCM", "Flutter"]
                ),
            ],
        ),

        WorkItem(
            id="backend_testing",
            name="Backend Evaluation & Stress Testing",
            category="project",
            description="Backend performance evaluation and stress-testing project.",
            technologies=["Backend Testing", "Performance Testing"],
            facts=[
                make_fact(
                    "backend_evaluation",
                    "Worked on backend load evaluation and stress-testing workflows.",
                    ["Performance Testing", "Backend"]
                ),
            ],
        ),
    ]


def initialize_profile() -> MasterProfile:
    if PROFILE_PATH.exists():
        profile = load_profile()
    else:
        profile = MasterProfile(name="Nasir Shahzad")

    default_skills = [
        "Flutter", "Dart", "Python",
        "Node.js", "Express.js", "MongoDB",
        "Firebase", "RAG", "FAISS",
        "AI Agents", "MCP", "BLoC",
        "Riverpod", "Provider", "GetX",
        "REST APIs", "Docker"
    ]

    profile.skills = list(dict.fromkeys(
        profile.skills + default_skills
    ))

    # Preserve existing records and custom edits
    existing = {
        item.id: item
        for item in profile.work_items
    }

    for item in get_career_data():
        if item.id not in existing:
            profile.work_items.append(item)
            continue

        current = existing[item.id]

        if not current.description:
            current.description = item.description

        current.technologies = list(dict.fromkeys(
            current.technologies + item.technologies
        ))

        existing_fact_ids = {
            fact.id for fact in current.facts
        }

        for fact in item.facts:
            if fact.id not in existing_fact_ids:
                current.facts.append(fact)

    save_profile(profile)
    return profile


if __name__ == "__main__":
    profile = initialize_profile()

    print("Profile:", profile.name)
    print("Projects & Experience:", len(profile.work_items))
    print(
        "Total Career Facts:",
        sum(len(item.facts) for item in profile.work_items)
    )
