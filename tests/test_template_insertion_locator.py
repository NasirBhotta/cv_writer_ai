
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document

from backend.app.services.template_insertion_locator import (
    locate_insertion_positions,
)


def add_entry(document, title):
    document.add_paragraph(title)

    bullet = document.add_paragraph()
    bullet.add_run("• ")
    bullet.add_run(
        "A complete test bullet for this entry."
    )


class LocatorTests(unittest.TestCase):

    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)

        self.path = (
            Path(folder.name) / "sample.docx"
        )

    def test_multiple_regions_require_review(self):
        document = Document()

        document.add_paragraph(
            "NASIR SHAHZAD | TECHNICAL CONTENT, "
            "AI & SELECTED PROJECTS"
        )

        document.add_paragraph(
            "RECENT MOBILE ENGINEERING EXPERIENCE"
        )

        add_entry(
            document,
            "GLOWSIMS — Mobile Developer",
        )

        document.add_paragraph(
            "EARLIER EXPERIENCE — CRIFLY"
        )

        add_entry(
            document,
            "Crifly — Flutter Developer",
        )

        document.add_paragraph(
            "AI AGENTS & RESEARCH"
        )

        add_entry(
            document,
            "Research Assistant Tool",
        )

        document.add_paragraph(
            "SELECTED ENGINEERING & AI PROJECTS"
        )

        add_entry(
            document,
            "BrainBee — AI-Powered Platform",
        )

        document.add_paragraph(
            "EDUCATION, SKILLS & LANGUAGES"
        )

        document.save(self.path)

        result = locate_insertion_positions(
            self.path
        )

        experience = result["locations"][
            "experience"
        ]

        projects = result["locations"][
            "project"
        ]

        self.assertTrue(
            experience["requires_review"]
        )

        self.assertTrue(
            projects["requires_review"]
        )

        self.assertEqual(
            len(experience["candidate_regions"]),
            2,
        )

        self.assertEqual(
            len(projects["candidate_regions"]),
            2,
        )

        self.assertNotIn(
            "NASIR SHAHZAD",
            str(result),
        )

    def test_unique_sections_can_suggest(self):
        document = Document()

        document.add_paragraph(
            "PROFESSIONAL EXPERIENCE"
        )

        add_entry(
            document,
            "GLOWSIMS — Developer Intern",
        )

        document.add_paragraph(
            "SELECTED PROJECTS"
        )

        add_entry(
            document,
            "BrainBee — Platform",
        )

        document.save(self.path)

        result = locate_insertion_positions(
            self.path
        )

        self.assertEqual(
            result["locations"]["experience"][
                "recommended_anchor"
            ],
            "PROFESSIONAL EXPERIENCE",
        )

        self.assertEqual(
            result["locations"]["project"][
                "recommended_style_from"
            ],
            "BrainBee — Platform",
        )

        self.assertFalse(
            result["locations"]["experience"][
                "requires_review"
            ]
        )

    def test_empty_section_needs_review_for_style(
        self,
    ):
        document = Document()

        document.add_paragraph(
            "PROFESSIONAL EXPERIENCE"
        )

        document.add_paragraph(
            "SELECTED PROJECTS"
        )

        add_entry(
            document,
            "BrainBee",
        )

        document.save(self.path)

        result = locate_insertion_positions(
            self.path
        )

        experience = result["locations"][
            "experience"
        ]

        self.assertTrue(
            experience["requires_review"]
        )

        self.assertEqual(
            experience["candidate_regions"][0][
                "style_examples"
            ],
            [],
        )

    def test_missing_file(self):
        with self.assertRaises(
            FileNotFoundError
        ):
            locate_insertion_positions(
                self.path
            )


if __name__ == "__main__":
    unittest.main()
