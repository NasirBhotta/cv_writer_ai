
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

import fitz

from docx import Document
from pydantic import ValidationError

from backend.app.models.page_layout_policy import (
    PageRequirements,
)

from backend.app.services.resume_layout_qa import (
    audit_resume_layout,
    export_docx_to_pdf,
    resolve_page_policy,
)


class PagePolicyTests(unittest.TestCase):

    def test_template_is_preference(self):
        decision = resolve_page_policy(
            PageRequirements(),
            template_pages=2,
        )

        self.assertEqual(
            decision.mode,
            "template_preference",
        )

        self.assertEqual(
            decision.preferred_pages,
            2,
        )

        self.assertIsNone(
            decision.exact_pages
        )

    def test_exact_user_page_requirement(self):
        decision = resolve_page_policy(
            PageRequirements(
                user_exact_pages=1
            ),
            template_pages=3,
        )

        self.assertEqual(
            decision.exact_pages,
            1,
        )

        self.assertEqual(
            decision.mode,
            "exact",
        )

    def test_employer_max_pages(self):
        decision = resolve_page_policy(
            PageRequirements(
                employer_max_pages=2
            )
        )

        self.assertEqual(
            decision.maximum_pages,
            2,
        )

    def test_two_maximums_take_stricter_value(self):
        decision = resolve_page_policy(
            PageRequirements(
                user_max_pages=3,
                employer_max_pages=2,
            )
        )

        self.assertEqual(
            decision.maximum_pages,
            2,
        )

    def test_conflicting_exact_requirements(self):
        decision = resolve_page_policy(
            PageRequirements(
                user_exact_pages=1,
                employer_exact_pages=2,
            )
        )

        self.assertTrue(
            decision.conflicts
        )

    def test_exact_greater_than_max_conflicts(self):
        decision = resolve_page_policy(
            PageRequirements(
                user_exact_pages=3,
                employer_max_pages=2,
            )
        )

        self.assertTrue(
            decision.conflicts
        )

    def test_no_constraint(self):
        self.assertEqual(
            resolve_page_policy(
                PageRequirements()
            ).mode,
            "unrestricted",
        )

    def test_zero_page_constraint_rejected(self):
        with self.assertRaises(
            ValidationError
        ):
            PageRequirements(
                user_exact_pages=0
            )


class LayoutAuditTests(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.root = Path(
            temp.name
        )

        self.docx = (
            self.root / "source.docx"
        )

        document = Document()

        document.add_paragraph(
            "A legitimate CV entry"
        )

        document.save(
            self.docx
        )

        self.source_bytes = (
            self.docx.read_bytes()
        )

    def pdf(
        self,
        name: str,
        pages: int,
    ) -> Path:
        path = self.root / name

        document = fitz.open()

        for index in range(pages):
            page = document.new_page()

            page.insert_text(
                (70, 70),
                f"Valid CV page {index + 1}",
            )

        document.save(path)
        document.close()

        return path

    def test_two_pages_matching_exact(self):
        pdf = self.pdf(
            "resume.pdf",
            2,
        )

        report = audit_resume_layout(
            source_docx=self.docx,
            pdf_path=pdf,
            requirements=PageRequirements(
                user_exact_pages=2
            ),
        )

        self.assertTrue(
            report.automated_checks_passed
        )

        self.assertTrue(
            report.visual_review_pending
        )

        self.assertFalse(
            report.ready_for_final_export
        )

        self.assertEqual(
            report.actual_pages,
            2,
        )

        self.assertEqual(
            self.docx.read_bytes(),
            self.source_bytes,
        )

    def test_exact_page_mismatch_fails(self):
        report = audit_resume_layout(
            source_docx=self.docx,
            pdf_path=self.pdf(
                "resume.pdf",
                3,
            ),
            requirements=PageRequirements(
                user_exact_pages=2
            ),
        )

        self.assertFalse(
            report.automated_checks_passed
        )

        self.assertIn(
            "!= required exactly",
            " ".join(report.errors),
        )

    def test_maximum_page_exceeded_fails(self):
        report = audit_resume_layout(
            source_docx=self.docx,
            pdf_path=self.pdf(
                "resume.pdf",
                3,
            ),
            requirements=PageRequirements(
                employer_max_pages=2
            ),
        )

        self.assertFalse(
            report.automated_checks_passed
        )

    def test_template_difference_warns_but_not_fails(
        self,
    ):
        report = audit_resume_layout(
            source_docx=self.docx,
            pdf_path=self.pdf(
                "resume.pdf",
                3,
            ),
            template_pdf_path=self.pdf(
                "template.pdf",
                2,
            ),
            requirements=PageRequirements(),
        )

        self.assertTrue(
            report.automated_checks_passed
        )

        self.assertTrue(
            any(
                "Template preference" in warning
                for warning in report.warnings
            )
        )

    def test_png_render(self):
        pdf = self.pdf(
            "resume.pdf",
            2,
        )

        images = (
            self.root / "images"
        )

        report = audit_resume_layout(
            source_docx=self.docx,
            pdf_path=pdf,
            requirements=PageRequirements(),
            render_dir=images,
        )

        self.assertEqual(
            len(report.page_images),
            2,
        )

        self.assertTrue(
            all(
                Path(path).is_file()
                for path in report.page_images
            )
        )

    def test_existing_png_is_not_overwritten(self):
        pdf = self.pdf(
            "resume.pdf",
            1,
        )

        images = (
            self.root / "images"
        )

        images.mkdir()

        (images / "page-1.png").write_bytes(
            b"safe"
        )

        with self.assertRaises(
            FileExistsError
        ):
            audit_resume_layout(
                source_docx=self.docx,
                pdf_path=pdf,
                requirements=PageRequirements(),
                render_dir=images,
            )

        self.assertEqual(
            (
                images / "page-1.png"
            ).read_bytes(),
            b"safe",
        )

    def test_manual_page_break_warning(self):
        document = Document(
            self.docx
        )

        document.add_page_break()
        document.save(
            self.docx
        )

        report = audit_resume_layout(
            source_docx=self.docx,
            pdf_path=self.pdf(
                "resume.pdf",
                2,
            ),
            requirements=PageRequirements(),
        )

        self.assertTrue(
            report.manual_page_break_paragraphs
        )

        self.assertTrue(
            any(
                "Manual page breaks" in warning
                for warning in report.warnings
            )
        )

    def test_converter_wont_overwrite(self):
        pdf = self.root / "already.pdf"

        pdf.write_bytes(
            b"keep"
        )

        with self.assertRaises(
            FileExistsError
        ):
            export_docx_to_pdf(
                self.docx,
                pdf,
            )

        self.assertEqual(
            pdf.read_bytes(),
            b"keep",
        )

    def test_missing_converter_returns_clear_error(
        self,
    ):
        with patch(
            "backend.app.services.resume_layout_qa."
            "_libreoffice_export",
            side_effect=RuntimeError(
                "not installed"
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "No PDF converter succeeded",
            ):
                export_docx_to_pdf(
                    self.docx,
                    self.root / "new.pdf",
                    engine="libreoffice",
                )


if __name__ == "__main__":
    unittest.main()
