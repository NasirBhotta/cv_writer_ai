
from pydantic import BaseModel, Field


class CareerFact(BaseModel):
    id: str
    description: str
    skills: list[str] = Field(default_factory=list)


class WorkItem(BaseModel):
    id: str
    name: str
    category: str  # project, internship, job
    description: str
    technologies: list[str] = Field(default_factory=list)
    facts: list[CareerFact] = Field(default_factory=list)


class MasterProfile(BaseModel):
    name: str
    email: str | None = None
    skills: list[str] = Field(default_factory=list)
    work_items: list[WorkItem] = Field(default_factory=list)


if __name__ == "__main__":
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
                        id="rag_chatbot",
                        description="Built a RAG-based chatbot",
                        skills=["RAG", "LLM"]
                    )
                ]
            )
        ]
    )

    print(profile.model_dump_json(indent=2))
