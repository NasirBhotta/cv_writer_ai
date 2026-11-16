
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document
from docx.oxml.ns import qn

from backend.app.services.template_inspector import (
    inspect_template,
)


class TemplateInspectorTests(unittest.TestCase):

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

        self.path = (
            Path(self.folder.name)
            / "custom_template.docx"
        )

        doc = Document()

        doc.add_paragraph(
            "Test Candidate",
            style="Title",
        )

        doc.add_paragraph(
            "Professional Summary",
            style="Heading 2",
        )

        doc.add_paragraph("Short about text.")

        table = doc.add_table(rows=1, cols=2)

        table.cell(0, 0).text = "Technical Skills"
        table.cell(0, 1).text = "Flutter, Python"

        doc.add_paragraph(
            "Work Experience",
            style="Heading 2",
        )

        doc.add_paragraph(
            "Education",
            style="Heading 2",
        )

        doc.sections[0].header.paragraphs[0].text = (
            "Contact details"
        )

        doc.save(self.path)

    def test_table_and_body_sections(self):
        report = inspect_template(self.path)

        sections = {
            hint.section
            for hint in report.section_hints
        }

        self.assertTrue(
            {
                "summary",
                "skills",
                "experience",
                "education",
            }.issubset(sections)
        )

        self.assertTrue(
            any(
                "/r0c0/" in block.block_id
                for block in report.blocks
            )
        )

        self.assertTrue(
            any(
                block.block_id.startswith("header0/")
                for block in report.blocks
            )
        )

        self.assertTrue(
            any(
                "tables" in warning
                for warning in report.warnings
            )
        )

    def test_original_is_unchanged(self):
        before = self.path.read_bytes()

        report = inspect_template(self.path)

        self.assertEqual(
            before,
            self.path.read_bytes(),
        )

        self.assertEqual(
            report.filename,
            self.path.name,
        )

    def test_column_detection(self):
        doc = Document(self.path)

        columns = doc.sections[0]._sectPr.find(
            qn("w:cols")
        )

        columns.set(qn("w:num"), "2")

        doc.save(self.path)

        report = inspect_template(self.path)

        self.assertEqual(
            report.layouts[0].columns,
            2,
        )

        self.assertTrue(
            any(
                "Multi-column" in warning
                for warning in report.warnings
            )
        )

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            inspect_template(
                self.path.parent / "missing.docx"
            )


if __name__ == "__main__":
    unittest.main()
