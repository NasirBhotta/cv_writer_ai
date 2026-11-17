
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document
from docx.oxml import OxmlElement
from docx.shared import Pt

from backend.app.services.template_inspector import (
    inspect_template,
)
from backend.app.services.template_mapper import (
    map_template,
)
from backend.app.services.template_edit_planner import (
    build_summary_edit_plan,
)
from backend.app.services.template_editor import (
    apply_template_edit_plan,
)


class TemplateEditorTests(unittest.TestCase):

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

        self.source = (
            Path(self.folder.name) / "input.docx"
        )
        self.output = (
            Path(self.folder.name) / "output.docx"
        )

        doc = Document()

        doc.add_paragraph("TEST CANDIDATE")

        # Empty paragraph tests block-ID accuracy.
        doc.add_paragraph("")

        doc.add_paragraph("PROFILE")

        summary = doc.add_paragraph()

        run = summary.add_run(
            "Original developer profile."
        )

        run.bold = False
        run.font.name = "Arial"
        run.font.size = Pt(10)

        summary.paragraph_format.space_after = Pt(3)

        doc.add_paragraph("WORK EXPERIENCE")
        doc.add_paragraph(
            "Original company history."
        )

        doc.save(self.source)

        self.report = inspect_template(
            self.source
        )

        self.mapping = map_template(
            self.report
        )

        self.plan = build_summary_edit_plan(
            self.report,
            self.mapping,
            "Updated profile tailored to the role.",
        )

    def test_original_untouched_and_formatted(self):
        before = self.source.read_bytes()

        result = apply_template_edit_plan(
            self.source,
            self.output,
            self.mapping,
            self.plan,
        )

        self.assertEqual(result, self.output)
        self.assertEqual(
            self.source.read_bytes(),
            before,
        )

        original = Document(self.source)
        output = Document(self.output)

        self.assertEqual(
            output.paragraphs[3].text,
            "Updated profile tailored to the role.",
        )

        self.assertEqual(
            output.paragraphs[4].text,
            original.paragraphs[4].text,
        )

        self.assertEqual(
            output.paragraphs[3].runs[0].font.name,
            "Arial",
        )

        self.assertEqual(
            output.paragraphs[3].runs[0].font.size,
            Pt(10),
        )

        self.assertEqual(
            output.paragraphs[3]
            .paragraph_format.space_after,
            Pt(3),
        )

    def test_uses_inspector_position_with_table(self):
        doc = Document()

        doc.add_paragraph("TEST CANDIDATE")

        table = doc.add_table(
            rows=1,
            cols=1,
        )

        table.cell(0, 0).text = (
            "Unrelated sidebar"
        )

        doc.add_paragraph("PROFILE")
        doc.add_paragraph("Original text.")
        doc.add_paragraph("EXPERIENCE")
        doc.add_paragraph("History")

        doc.save(self.source)

        report = inspect_template(self.source)
        mapping = map_template(report)

        plan = build_summary_edit_plan(
            report,
            mapping,
            "New text.",
        )

        self.assertEqual(
            plan.edits[0].block_id,
            "body/3",
        )

        apply_template_edit_plan(
            self.source,
            self.output,
            mapping,
            plan,
        )

        self.assertEqual(
            Document(self.output).paragraphs[2].text,
            "New text.",
        )

    def test_rejects_changed_template(self):
        doc = Document(self.source)

        doc.paragraphs[0].text = (
            "DIFFERENT PERSON"
        )

        doc.save(self.source)

        with self.assertRaisesRegex(
            ValueError,
            "SHA-256",
        ):
            apply_template_edit_plan(
                self.source,
                self.output,
                self.mapping,
                self.plan,
            )

        self.assertFalse(self.output.exists())

    def test_rejects_multiple_runs(self):
        doc = Document(self.source)

        doc.paragraphs[3].add_run(
            " Additional words"
        )

        doc.save(self.source)

        report = inspect_template(self.source)
        mapping = map_template(report)

        plan = build_summary_edit_plan(
            report,
            mapping,
            "New short summary.",
        )

        with self.assertRaisesRegex(
            ValueError,
            "multiple runs",
        ):
            apply_template_edit_plan(
                self.source,
                self.output,
                mapping,
                plan,
            )

        self.assertFalse(self.output.exists())

    def test_rejects_hyperlink(self):
        doc = Document(self.source)

        doc.paragraphs[3]._p.append(
            OxmlElement("w:hyperlink")
        )

        doc.save(self.source)

        report = inspect_template(self.source)
        mapping = map_template(report)

        plan = build_summary_edit_plan(
            report,
            mapping,
            "New short summary.",
        )

        with self.assertRaisesRegex(
            ValueError,
            "unsupported Word elements",
        ):
            apply_template_edit_plan(
                self.source,
                self.output,
                mapping,
                plan,
            )

        self.assertFalse(self.output.exists())

    def test_rejects_mismatched_old_text(self):
        self.plan.edits[0].old_text = (
            "Incorrect original"
        )

        with self.assertRaisesRegex(
            ValueError,
            "Original summary text",
        ):
            apply_template_edit_plan(
                self.source,
                self.output,
                self.mapping,
                self.plan,
            )

    def test_rejects_existing_output(self):
        self.output.write_text(
            "already here"
        )

        with self.assertRaises(
            FileExistsError
        ):
            apply_template_edit_plan(
                self.source,
                self.output,
                self.mapping,
                self.plan,
            )

        self.assertEqual(
            self.output.read_text(),
            "already here",
        )

    def test_rejects_replacing_input(self):
        with self.assertRaisesRegex(
            ValueError,
            "Output must differ",
        ):
            apply_template_edit_plan(
                self.source,
                self.source,
                self.mapping,
                self.plan,
            )

    def test_rejects_multiline_text(self):
        with self.assertRaisesRegex(
            ValueError,
            "single clean paragraph",
        ):
            build_summary_edit_plan(
                self.report,
                self.mapping,
                "A new\nline",
            )

    def test_rejects_reviewed_summary(self):
        for region in self.mapping.regions:
            if region.section == "summary":
                region.needs_review = True

        with self.assertRaisesRegex(
            ValueError,
            "Cannot safely locate",
        ):
            build_summary_edit_plan(
                self.report,
                self.mapping,
                "New summary",
            )


if __name__ == "__main__":
    unittest.main()
