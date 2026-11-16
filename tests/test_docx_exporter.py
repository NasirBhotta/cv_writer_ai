
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document

from backend.app.models.resume_document import (
    ResumeDocument,
    ResumeEntry,
    ResumeBullet,
    SkillGroup,
)
from backend.app.services.docx_exporter import (
    export_resume_docx,
)


class DocxExporterTests(unittest.TestCase):

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)
        self.template = self.root / "template.docx"
        self.output = self.root / "resume.docx"

        self.context = {
            "candidate": {
                "name": "Test Candidate",
                "email": "test@example.com",
                "skills": ["Flutter", "Python", "RAG"],
                "education": [
                    {
                        "institution": "Test University",
                        "degree": "BS Computer Science",
                        "graduation_year": 2026,
                        "cgpa": 3.23,
                    }
                ],
            },
            "selected_fact_ids": [
                "c1", "g1", "b1"
            ],
            "work_items": [
                {
                    "id": "crifly",
                    "name": "Crifly",
                    "organization": "Crifly",
                    "role": "Flutter Developer",
                    "category": "employment",
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
                    "organization": "GLOWSIMS",
                    "role": "Mobile App Intern",
                    "category": "internship",
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
                    "selected_facts": [
                        {
                            "id": "b1",
                            "description": "Built RAG retrieval."
                        }
                    ],
                },
            ],
        }

        self.resume = ResumeDocument(
            headline="Junior Full-Stack AI Engineer",
            summary=(
                "Software engineer with Flutter, Python "
                "and RAG experience across mobile and "
                "backend projects."
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

    def create_template(self, include_education=True):
        document = Document()

        # Simulate a placeholder split across Word runs.
        p = document.add_paragraph("Candidate: ")
        p.add_run("{{NA")
        p.add_run("ME}}")

        document.add_paragraph("{{HEADLINE}}")
        document.add_paragraph("{{CONTACT}}")

        document.add_heading(
            "Professional Summary", level=2
        )
        document.add_paragraph("{{SUMMARY}}")

        document.add_heading(
            "Technical Skills", level=2
        )
        document.add_paragraph("{{SKILLS}}")

        document.add_heading(
            "Professional Experience", level=2
        )
        document.add_paragraph("{{EXPERIENCE}}")

        document.add_heading(
            "Selected Projects", level=2
        )
        document.add_paragraph("{{PROJECTS}}")

        document.add_heading("Education", level=2)

        if include_education:
            document.add_paragraph("{{EDUCATION}}")

        document.save(self.template)

    def test_successful_export(self):
        self.create_template()

        output = export_resume_docx(
            self.resume,
            self.context,
            self.template,
            self.output,
        )

        self.assertTrue(output.is_file())

        result = Document(output)

        text = "\n".join(
            p.text for p in result.paragraphs
        )

        self.assertIn(
            "Candidate: Test Candidate", text
        )
        self.assertIn("Crifly", text)
        self.assertIn("GLOWSIMS", text)
        self.assertIn("BrainBee", text)
        self.assertIn("Test University", text)
        self.assertNotIn("{{", text)

    def test_missing_placeholder_rejected(self):
        self.create_template(
            include_education=False
        )

        with self.assertRaises(ValueError):
            export_resume_docx(
                self.resume,
                self.context,
                self.template,
                self.output,
            )

    def test_wrong_fact_rejected(self):
        self.create_template()

        # Assign the GLOWSIMS fact to Crifly.
        self.resume.entries[0].bullets[0].fact_id = "g1"

        with self.assertRaises(ValueError):
            export_resume_docx(
                self.resume,
                self.context,
                self.template,
                self.output,
            )

    def test_original_template_unchanged(self):
        self.create_template()

        export_resume_docx(
            self.resume,
            self.context,
            self.template,
            self.output,
        )

        original = Document(self.template)

        text = "\n".join(
            p.text for p in original.paragraphs
        )

        self.assertIn("{{EXPERIENCE}}", text)
        self.assertIn("{{PROJECTS}}", text)


if __name__ == "__main__":
    unittest.main()
