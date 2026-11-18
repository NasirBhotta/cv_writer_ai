
import json
import unittest

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from docx import Document

from backend.app.services.resume_content_audit import (
    audit_resume_content,
)
from backend.app.services.snapshot_semantic_recheck import (
    document_hash,
)


class ResumeContentAuditTests(unittest.TestCase):

    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)

        root = Path(folder.name)

        self.source = root / "assembled.docx"
        self.snapshot_path = root / "approved.json"
        self.profile_path = root / "profile.json"

        self.profile = {
            "work_items": [
                {
                    "id": "crifly_developer",
                    "name": (
                        "Crifly — Part-Time "
                        "Full-Stack Flutter Developer"
                    ),
                    "organization": "Crifly",
                    "role": (
                        "Part-Time Full-Stack "
                        "Flutter Developer"
                    ),
                    "category": "job",
                    "facts": [
                        {
                            "id": "c1",
                            "description": (
                                "Integrated verified REST APIs "
                                "for mobile applications."
                            ),
                        },
                        {
                            "id": "c2",
                            "description": (
                                "Built Flutter mobile screens "
                                "for retail applications."
                            ),
                        },
                    ],
                },
                {
                    "id": "brainbee",
                    "name": "BrainBee — AI Platform",
                    "category": "project",
                    "facts": [
                        {
                            "id": "b1",
                            "description": (
                                "Developed textbook-grounded "
                                "RAG with FAISS retrieval."
                            ),
                        }
                    ],
                },
                {
                    "id": "legacy",
                    "name": "Old Portfolio Project",
                    "category": "project",
                    "facts": [
                        {
                            "id": "l1",
                            "description": (
                                "Created a sample project "
                                "for experimentation."
                            ),
                        }
                    ],
                },
            ]
        }

        self.resume = {
            "headline": "Software Engineer",
            "summary": (
                "Software engineer experienced in "
                "mobile application development "
                "and retrieval systems."
            ),
            "skill_groups": [
                {
                    "title": "Engineering",
                    "skills": [
                        "Flutter",
                        "Python",
                    ],
                }
            ],
            "entries": [
                {
                    "work_id": "crifly_developer",
                    "section": "experience",
                    "bullets": [
                        {
                            "fact_id": "c1",
                            "text": (
                                "Integrated verified REST APIs "
                                "for mobile applications."
                            ),
                        }
                    ],
                },
                {
                    "work_id": "brainbee",
                    "section": "project",
                    "bullets": [
                        {
                            "fact_id": "b1",
                            "text": (
                                "Developed textbook-grounded "
                                "RAG with FAISS retrieval."
                            ),
                        }
                    ],
                },
            ],
        }

        self.profile_path.write_text(
            json.dumps(self.profile),
            encoding="utf-8",
        )

        self.snapshot = {
            "resume_document": self.resume,
            "profile_sha256": sha256(
                self.profile_path.read_bytes()
            ).hexdigest(),
            "quality_passed": True,
            "run_status": "rechecked_approved",
            "selected_fact_ids": [
                "c1",
                "c2",
                "b1",
            ],
            "semantic_recheck": {
                "passed": True,
                "document_sha256": document_hash(
                    self.resume
                ),
            },
        }

        self._write_snapshot()
        self._make_docx()

    def _write_snapshot(self):
        self.snapshot_path.write_text(
            json.dumps(self.snapshot),
            encoding="utf-8",
        )

    def _make_docx(
        self,
        *,
        extra=False,
        omit_bullet=False,
        duplicate=False,
        wrong_bullet=False,
    ):
        document = Document()

        document.add_paragraph(
            "PROFESSIONAL EXPERIENCE"
        )

        document.add_paragraph(
            "Part-Time Full-Stack Flutter Developer "
            "— Crifly\tJan 2025 – Feb 2026"
        )

        if duplicate:
            document.add_paragraph(
                "Part-Time Full-Stack Flutter "
                "Developer — Crifly"
            )

        document.add_paragraph(
            (
                "• Completely unrelated bullet."
                if wrong_bullet
                else (
                    "• Integrated verified REST APIs "
                    "for mobile applications."
                )
            )
        )

        if extra:
            document.add_paragraph(
                "• Extra outdated achievement claim."
            )

        document.add_paragraph(
            "SELECTED PROJECTS"
        )

        document.add_paragraph(
            "BrainBee — AI Platform"
        )

        if not omit_bullet:
            document.add_paragraph(
                "• Developed textbook-grounded "
                "RAG with FAISS retrieval."
            )

        document.add_paragraph(
            "Old Portfolio Project"
        )

        document.add_paragraph(
            "• Created a sample project "
            "for experimentation."
        )

        document.add_paragraph(
            "EDUCATION"
        )

        document.save(self.source)

    def _audit(
        self,
        jd=(
            "Hiring Python Flutter RAG developer, "
            "REST APIs experience"
        ),
    ):
        return audit_resume_content(
            source_path=self.source,
            snapshot_path=self.snapshot_path,
            profile_path=self.profile_path,
            job_description=jd,
        )

    def test_fully_approved_entries_covered(self):
        result = self._audit()

        self.assertTrue(
            result.approved_content_complete
        )

        self.assertEqual(
            [
                entry.status
                for entry in result.entries
            ],
            ["pass", "pass"],
        )

        self.assertEqual(
            len(result.approved_work_ids),
            2,
        )

    def test_selected_fact_omission_reported_not_deleted(
        self,
    ):
        result = self._audit()

        self.assertEqual(
            [
                fact.fact_id
                for fact in result.omitted_selected_facts
            ],
            ["c2"],
        )

        self.assertTrue(
            result.approved_content_complete
        )

    def test_retained_template_only_flagged_for_review(
        self,
    ):
        result = self._audit()

        self.assertEqual(
            [
                item.work_id
                for item in result.retained_template_entries
            ],
            ["legacy"],
        )

        self.assertFalse(
            result.ready_for_final_export
        )

    def test_missing_approved_bullet_fails(self):
        self._make_docx(
            omit_bullet=True
        )

        result = self._audit()

        self.assertFalse(
            result.approved_content_complete
        )

        self.assertEqual(
            result.entries[1].missing_fact_ids,
            ["b1"],
        )

    def test_duplicate_heading_fails(self):
        self._make_docx(
            duplicate=True
        )

        result = self._audit()

        self.assertFalse(
            result.approved_content_complete
        )

        self.assertEqual(
            result.entries[0].heading_count,
            2,
        )

    def test_extra_bullet_fails(self):
        self._make_docx(
            extra=True
        )

        result = self._audit()

        self.assertFalse(
            result.approved_content_complete
        )

        self.assertEqual(
            len(
                result.entries[0].extra_bullets
            ),
            1,
        )

    def test_wrong_bullet_under_heading_fails(
        self,
    ):
        self._make_docx(
            wrong_bullet=True
        )

        result = self._audit()

        self.assertFalse(
            result.approved_content_complete
        )

        self.assertIn(
            "c1",
            result.entries[0].missing_fact_ids,
        )

    def test_semantic_fingerprint_change_rejected(
        self,
    ):
        self.snapshot["resume_document"][
            "entries"
        ][0]["bullets"][0]["text"] = (
            "Tampered claim with no semantic review."
        )

        self._write_snapshot()

        with self.assertRaisesRegex(
            ValueError,
            "semantic approval",
        ):
            self._audit()

    def test_profile_sha_change_rejected(self):
        self.profile_path.write_text(
            "{}",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "SHA-256",
        ):
            self._audit()

    def test_unselected_bullet_rejected(self):
        self.snapshot[
            "selected_fact_ids"
        ] = [
            "c1",
            "c2",
        ]

        self._write_snapshot()

        with self.assertRaisesRegex(
            ValueError,
            "Unsupported fact ownership",
        ):
            self._audit()

    def test_jd_absent_is_not_a_relevance_pass(
        self,
    ):
        result = self._audit(
            jd=None
        )

        self.assertFalse(
            result.jd_relevance_reviewed
        )

        self.assertTrue(
            any(
                "No job description" in warning
                for warning in result.warnings
            )
        )

    def test_source_document_is_unchanged(self):
        before = self.source.read_bytes()

        self._audit()

        self.assertEqual(
            self.source.read_bytes(),
            before,
        )

    def test_no_unselected_fact_auto_included(
        self,
    ):
        result = self._audit(
            jd="experimental project"
        )

        self.assertEqual(
            result.approved_work_ids,
            [
                "crifly_developer",
                "brainbee",
            ],
        )

        self.assertTrue(
            any(
                hint.fact_id == "l1"
                for hint in (
                    result
                    .potentially_relevant_unselected_facts
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
