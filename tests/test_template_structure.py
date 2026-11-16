
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document
from docx.enum.text import WD_BREAK

from backend.app.services.template_inspector import (
    inspect_template,
)
from backend.app.services.template_mapper import (
    map_template,
)
from backend.app.services.template_structure import (
    validate_template_mapping,
)


class TemplateStructureTests(unittest.TestCase):

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

        self.path = (
            Path(self.folder.name) / "resume.docx"
        )

        doc = Document()

        doc.add_paragraph("TEST CANDIDATE")
        doc.add_paragraph("DEVELOPER | AI")
        doc.add_paragraph("contact@example.com")

        doc.add_paragraph("PROFILE")
        doc.add_paragraph("Experienced developer.")

        doc.add_paragraph("WORK EXPERIENCE")
        doc.add_paragraph(
            "Software Engineer — Example Corp"
        )
        doc.add_paragraph("Integrated REST APIs.")

        # Simulate an explicit Word page break.
        doc.add_paragraph().add_run().add_break(
            WD_BREAK.PAGE
        )

        doc.add_paragraph(
            "TEST CANDIDATE | SELECTED PROJECTS"
        )
        doc.add_paragraph(
            "portfolio.example.com | github.com/test"
        )

        doc.add_paragraph(
            "EDUCATION, SKILLS & LANGUAGES"
        )
        doc.add_paragraph(
            "BS Computer Science — Example University"
        )
        doc.add_paragraph(
            "Mobile & SDKs: Flutter, Dart"
        )
        doc.add_paragraph(
            "Certifications: Python Certificate"
        )
        doc.add_paragraph(
            "Unexpected note needing review"
        )

        doc.save(self.path)

        self.report = inspect_template(self.path)
        self.mapping = map_template(self.report)

    def test_repeated_header_protected(self):
        self.assertIn(
            "body/9",
            self.mapping.protected_block_ids,
        )
        self.assertIn(
            "body/10",
            self.mapping.protected_block_ids,
        )

        all_content = {
            block_id
            for region in self.mapping.regions
            for block_id in region.content_block_ids
        }

        self.assertFalse(
            all_content.intersection(
                self.mapping.protected_block_ids
            )
        )

    def test_mixed_section_classification(self):
        region = next(
            item
            for item in self.mapping.regions
            if item.section == "mixed"
        )

        categories = [
            item.section
            for item in region.sub_blocks
        ]

        self.assertEqual(
            categories,
            [
                "education",
                "skills",
                "certifications",
                "unknown",
            ],
        )

        self.assertTrue(region.needs_review)

    def test_invalid_mapping_rejected(self):
        errors = validate_template_mapping(
            self.report,
            self.mapping,
        )

        self.assertEqual(errors, [])

        # Deliberately assign a protected header
        # to normal section content.
        self.mapping.regions[0].content_block_ids.append(
            self.mapping.protected_block_ids[0]
        )

        errors = validate_template_mapping(
            self.report,
            self.mapping,
        )

        self.assertTrue(
            any("Protected" in error for error in errors)
        )

    def test_different_template(self):
        doc = Document()

        doc.add_paragraph("OTHER CANDIDATE")
        doc.add_paragraph(
            "PROFESSIONAL SUMMARY",
            style="Heading 2",
        )
        doc.add_paragraph("Experienced engineer.")
        doc.add_paragraph(
            "PROJECTS",
            style="Heading 2",
        )
        doc.add_paragraph("Project A")

        other = (
            Path(self.folder.name) / "other.docx"
        )
        doc.save(other)

        report = inspect_template(other)
        mapping = map_template(report)

        self.assertEqual(
            mapping.protected_block_ids,
            [],
        )

        self.assertEqual(
            [r.section for r in mapping.regions],
            ["summary", "projects"],
        )

    def test_table_template_warning(self):
        doc = Document()
        doc.add_paragraph("ANOTHER CANDIDATE")

        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "WORK EXPERIENCE"
        table.cell(0, 1).text = "Example experience"

        other = (
            Path(self.folder.name) / "sidebar.docx"
        )
        doc.save(other)

        report = inspect_template(other)
        mapping = map_template(report)

        self.assertTrue(
            any(
                "Table-cell" in warning
                for warning in mapping.warnings
            )
        )


if __name__ == "__main__":
    unittest.main()
