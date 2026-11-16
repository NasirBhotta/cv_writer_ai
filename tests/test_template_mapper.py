
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document

from backend.app.services.template_inspector import (
    inspect_template,
)
from backend.app.services.template_mapper import (
    map_template,
)


class TemplateMapperTests(unittest.TestCase):

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

        self.path = (
            Path(self.folder.name) / "resume.docx"
        )

        doc = Document()

        doc.add_paragraph("TEST CANDIDATE")
        doc.add_paragraph("FLUTTER | AI | MOBILE")
        doc.add_paragraph("test@example.com")
        doc.add_paragraph("Portfolio | GitHub")

        doc.add_paragraph("PROFILE")
        doc.add_paragraph("Software developer profile.")

        doc.add_paragraph("FEATURED TECHNICAL WORK SAMPLE")
        doc.add_paragraph("On-device AI investigation")

        doc.add_paragraph("RECENT MOBILE ENGINEERING EXPERIENCE")
        doc.add_paragraph("GLOWSIMS — Mobile Intern")

        doc.add_paragraph("EARLIER EXPERIENCE")
        doc.add_paragraph("Crifly — Flutter Developer")

        # Simulate a repeated header on page two.
        doc.add_paragraph(
            "TEST CANDIDATE | AI & SELECTED PROJECTS"
        )

        doc.add_paragraph("AI AGENTS & RESEARCH")
        doc.add_paragraph("Research agent")

        doc.add_paragraph("SELECTED ENGINEERING PROJECTS")
        doc.add_paragraph("BrainBee")

        doc.add_paragraph("EDUCATION, SKILLS & LANGUAGES")
        doc.add_paragraph("BS Computer Science")

        doc.save(self.path)

        self.report = inspect_template(self.path)
        self.mapping = map_template(self.report)

    def test_custom_headings(self):
        sections = [
            region.section
            for region in self.mapping.regions
        ]

        self.assertIn("summary", sections)
        self.assertIn("featured_work", sections)
        self.assertIn("experience", sections)
        self.assertIn("projects", sections)
        self.assertIn("mixed", sections)

    def test_content_boundaries(self):
        profile = next(
            region
            for region in self.mapping.regions
            if region.section == "summary"
        )

        self.assertEqual(
            profile.content_block_ids,
            ["body/5"],
        )

    def test_mixed_section_needs_review(self):
        mixed = next(
            region
            for region in self.mapping.regions
            if region.section == "mixed"
        )

        self.assertTrue(mixed.needs_review)

        self.assertEqual(
            set(mixed.possible_sections),
            {"skills", "education", "languages"},
        )

    def test_repeated_page_title_not_section(self):
        headings = [
            region.heading_text
            for region in self.mapping.regions
        ]

        self.assertNotIn(
            "TEST CANDIDATE | AI & SELECTED PROJECTS",
            headings,
        )

    def test_original_document_unchanged(self):
        before = self.path.read_bytes()

        map_template(self.report)

        after = self.path.read_bytes()

        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
