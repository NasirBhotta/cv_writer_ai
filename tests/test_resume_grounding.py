
import unittest

from backend.app.models.resume_document import (
    ResumeDocument,
    ResumeEntry,
    ResumeBullet,
    SkillGroup,
)
from backend.app.services.resume_grounding import (
    validate_resume_document,
    build_grounding_pairs,
)
from backend.app.services.career_validator import (
    _professional_section,
)


def sample_context():
    return {
        "candidate": {
            "name": "Test Candidate",
            "skills": ["Flutter", "Python", "RAG"],
        },
        "selected_fact_ids": ["c1", "g1", "b1"],
        "work_items": [
            {
                "id": "crifly",
                "name": "Crifly",
                "category": "employment",
                "role": "Flutter Developer",
                "selected_facts": [
                    {
                        "id": "c1",
                        "description": "Integrated REST APIs."
                    }
                ],
            },
            {
                "id": "glowsims",
                "name": "GLOWSIMS",
                "category": "internship",
                "role": "Mobile App Intern",
                "selected_facts": [
                    {
                        "id": "g1",
                        "description": "Optimized API queries."
                    }
                ],
            },
            {
                "id": "brainbee",
                "name": "BrainBee",
                "category": "project",
                "role": "Co-developer",
                "selected_facts": [
                    {
                        "id": "b1",
                        "description": "Built RAG retrieval."
                    }
                ],
            },
        ],
    }


def sample_document():
    return ResumeDocument(
        headline="Junior Full-Stack AI Engineer",
        summary=(
            "Software engineer with Flutter, Python "
            "and RAG project experience focused "
            "on backend integration."
        ),
        skill_groups=[
            SkillGroup(
                title="Technical Skills",
                skills=["Flutter", "Python", "RAG"],
            )
        ],
        entries=[
            ResumeEntry(
                work_id="crifly",
                section="experience",
                bullets=[
                    ResumeBullet(
                        fact_id="c1",
                        text="Integrated REST API endpoints."
                    )
                ],
            ),
            ResumeEntry(
                work_id="glowsims",
                section="experience",
                bullets=[
                    ResumeBullet(
                        fact_id="g1",
                        text="Optimized backend API queries."
                    )
                ],
            ),
            ResumeEntry(
                work_id="brainbee",
                section="project",
                bullets=[
                    ResumeBullet(
                        fact_id="b1",
                        text="Built RAG retrieval workflows."
                    )
                ],
            ),
        ],
    )


class ResumeGroundingTests(unittest.TestCase):

    def setUp(self):
        self.context = sample_context()
        self.document = sample_document()

    def test_valid_document(self):
        errors = validate_resume_document(
            self.document, self.context
        )
        self.assertEqual(errors, [])

    def test_wrong_project_fact(self):
        self.document.entries[2].bullets[0].fact_id = "c1"

        errors = validate_resume_document(
            self.document, self.context
        )

        self.assertTrue(
            any("does not belong" in e for e in errors)
        )

    def test_unknown_skill(self):
        self.document.skill_groups[0].skills.append(
            "Quantum Computing"
        )

        errors = validate_resume_document(
            self.document, self.context
        )

        self.assertTrue(
            any("Unknown profile skill" in e for e in errors)
        )

    def test_missing_professional_experience(self):
        self.document.entries = [
            entry for entry in self.document.entries
            if entry.work_id != "glowsims"
        ]

        errors = validate_resume_document(
            self.document, self.context
        )

        self.assertTrue(
            any("Insufficient professional" in e for e in errors)
        )

    def test_wrong_section(self):
        self.document.entries[2].section = "experience"

        errors = validate_resume_document(
            self.document, self.context
        )

        self.assertTrue(
            any("Wrong section" in e for e in errors)
        )

    def test_grounding_pairs(self):
        pairs = build_grounding_pairs(
            self.document, self.context
        )

        self.assertEqual(len(pairs), 3)
        self.assertEqual(pairs[0]["fact_id"], "c1")
        self.assertEqual(
            pairs[0]["source_fact"],
            "Integrated REST APIs."
        )

    def test_professional_section_headings(self):
        draft = """
## Professional Experience

### Crifly
- Integrated APIs.

### GLOWSIMS
- Improved performance.

## Selected Projects

### BrainBee
- Built RAG.
"""
        section = _professional_section(draft)

        self.assertIn("Crifly", section)
        self.assertIn("GLOWSIMS", section)
        self.assertNotIn("BrainBee", section)


if __name__ == "__main__":
    unittest.main()
