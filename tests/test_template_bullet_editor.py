import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document
from docx.oxml import OxmlElement
from docx.shared import Pt

from backend.app.services.template_inspector import inspect_template
from backend.app.services.template_mapper import map_template
from backend.app.services.template_edit_planner import (
    build_resume_edit_plan,
    build_bullet_edit_plan,
    build_summary_edit_plan,
)
from backend.app.services.template_editor import apply_template_edit_plan


class TemplateBulletEditorTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.source = Path(folder.name) / "source.docx"
        self.output = Path(folder.name) / "output.docx"

        doc = Document()
        doc.add_paragraph("TEST CANDIDATE")
        doc.add_paragraph("")
        doc.add_paragraph("PROFILE")
        doc.add_paragraph("Original profile text.")
        doc.add_paragraph("WORK EXPERIENCE")
        doc.add_paragraph("Example Corp — Engineer")

        experience = doc.add_paragraph()
        marker = experience.add_run("• ")
        marker.bold = True
        body = experience.add_run("Optimized a backend API.")
        body.font.name = "Arial"
        body.font.size = Pt(10)

        doc.add_paragraph("PROJECTS")
        doc.add_paragraph("Example Project")
        project = doc.add_paragraph()
        project.add_run("• ").bold = True
        project.add_run("Built a learning tool.")
        doc.save(self.source)

        self.report = inspect_template(self.source)
        self.mapping = map_template(self.report)
        self.experience_id = "body/6"
        self.project_id = "body/9"

    def _fresh(self):
        report = inspect_template(self.source)
        return report, map_template(report)

    def test_summary_experience_project_in_one_pass(self):
        before = self.source.read_bytes()
        plan = build_resume_edit_plan(
            self.report, self.mapping,
            summary="Tailored Python and Flutter profile.",
            bullet_replacements={
                self.experience_id: "Improved an existing REST endpoint.",
                self.project_id: "Implemented a student learning feature.",
            },
        )
        result = apply_template_edit_plan(
            self.source, self.output, self.mapping, plan
        )
        self.assertEqual(result, self.output)
        self.assertEqual(before, self.source.read_bytes())
        doc = Document(self.output)
        self.assertEqual(doc.paragraphs[3].text, "Tailored Python and Flutter profile.")
        self.assertEqual(doc.paragraphs[6].text, "• Improved an existing REST endpoint.")
        self.assertEqual(doc.paragraphs[9].text, "• Implemented a student learning feature.")
        self.assertTrue(doc.paragraphs[6].runs[0].bold)
        self.assertEqual(doc.paragraphs[6].runs[0].text, "• ")
        self.assertEqual(doc.paragraphs[6].runs[1].font.name, "Arial")
        self.assertEqual(doc.paragraphs[6].runs[1].font.size, Pt(10))
        self.assertEqual(doc.paragraphs[5].text, "Example Corp — Engineer")

    def test_uniform_body_runs_supported(self):
        doc = Document(self.source)
        doc.paragraphs[9].add_run(" More detail.")
        doc.save(self.source)
        report, mapping = self._fresh()
        plan = build_bullet_edit_plan(report, mapping, {
            self.project_id: "A replacement project bullet.",
        })
        apply_template_edit_plan(self.source, self.output, mapping, plan)
        output = Document(self.output)
        self.assertEqual(output.paragraphs[9].text, "• A replacement project bullet.")
        self.assertEqual(output.paragraphs[9].runs[2].text, "")

    def test_mixed_body_format_requires_review(self):
        doc = Document(self.source)
        doc.paragraphs[9].add_run(" Extra bold text.").bold = True
        doc.save(self.source)
        report, mapping = self._fresh()
        plan = build_bullet_edit_plan(report, mapping, {
            self.project_id: "Replacement text.",
        })
        with self.assertRaisesRegex(ValueError, "mixed formatting"):
            apply_template_edit_plan(self.source, self.output, mapping, plan)
        self.assertFalse(self.output.exists())

    def test_no_nonbullet_title_edit(self):
        with self.assertRaisesRegex(ValueError, "not a bullet"):
            build_bullet_edit_plan(
                self.report, self.mapping,
                {"body/5": "Trying to replace entry title"},
            )

    def test_reviewed_region_rejected(self):
        for region in self.mapping.regions:
            if region.section == "projects":
                region.needs_review = True
        with self.assertRaisesRegex(ValueError, "confirmed projects"):
            build_bullet_edit_plan(
                self.report, self.mapping,
                {self.project_id: "New project description"},
            )

    def test_protected_region_rejected(self):
        self.mapping.protected_block_ids.append(self.experience_id)
        with self.assertRaisesRegex(ValueError, "protected"):
            build_bullet_edit_plan(
                self.report, self.mapping,
                {self.experience_id: "New bullet"},
            )

    def test_old_text_mismatch_rejected(self):
        plan = build_bullet_edit_plan(
            self.report, self.mapping,
            {self.experience_id: "New bullet"},
        )
        plan.edits[0].old_text = "wrong source"
        with self.assertRaisesRegex(ValueError, "Original bullet text"):
            apply_template_edit_plan(self.source, self.output, self.mapping, plan)

    def test_modified_template_rejected(self):
        plan = build_bullet_edit_plan(
            self.report, self.mapping,
            {self.experience_id: "New bullet"},
        )
        doc = Document(self.source)
        doc.paragraphs[0].text = "ANOTHER CANDIDATE"
        doc.save(self.source)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            apply_template_edit_plan(self.source, self.output, self.mapping, plan)
        self.assertFalse(self.output.exists())

    def test_hyperlink_in_bullet_rejected(self):
        doc = Document(self.source)
        doc.paragraphs[6]._p.append(OxmlElement("w:hyperlink"))
        doc.save(self.source)
        report, mapping = self._fresh()
        plan = build_bullet_edit_plan(report, mapping, {
            self.experience_id: "New bullet.",
        })
        with self.assertRaisesRegex(ValueError, "unsupported Word elements"):
            apply_template_edit_plan(self.source, self.output, mapping, plan)
        self.assertFalse(self.output.exists())

    def test_all_or_nothing_two_bullets(self):
        doc = Document(self.source)
        doc.paragraphs[9].add_run(" Strong text").bold = True
        doc.save(self.source)
        report, mapping = self._fresh()
        plan = build_bullet_edit_plan(report, mapping, {
            self.experience_id: "Safe replacement",
            self.project_id: "Unsafe replacement",
        })
        before = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, "mixed formatting"):
            apply_template_edit_plan(self.source, self.output, mapping, plan)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse(self.output.exists())

    def test_empty_edits_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one edit"):
            build_resume_edit_plan(self.report, self.mapping)

    def test_bullet_marker_not_doubled(self):
        with self.assertRaisesRegex(ValueError, "omit the bullet marker"):
            build_bullet_edit_plan(
                self.report, self.mapping,
                {self.experience_id: "• Already marked"},
            )

    def test_previous_summary_api_works(self):
        plan = build_summary_edit_plan(
            self.report, self.mapping, "Updated summary."
        )
        apply_template_edit_plan(self.source, self.output, self.mapping, plan)
        self.assertEqual(Document(self.output).paragraphs[3].text, "Updated summary.")


if __name__ == "__main__":
    unittest.main()
