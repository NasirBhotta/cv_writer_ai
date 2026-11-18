
import json
import unittest

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from docx import Document

from backend.app.services.safe_entry_inserter import (
    insert_missing_approved_entries,
)
from backend.app.services.snapshot_semantic_recheck import (
    document_hash,
)


class SafeEntryInsertionTests(unittest.TestCase):

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.root = Path(temp.name)
        self.source = self.root / "base.docx"
        self.output = self.root / "with_entries.docx"
        self.snapshot_path = self.root / "snapshot.json"
        self.profile_path = self.root / "master_profile.json"

        # Create a small but real Word template.
        document = Document()

        document.add_paragraph("NASIR SHAHZAD")
        document.add_paragraph(
            "RECENT MOBILE ENGINEERING EXPERIENCE"
        )

        heading = document.add_paragraph()
        heading.add_run(
            "Mobile App Development Intern — GLOWSIMS"
        ).bold = True
        heading.add_run("\tFeb 2026 – May 2026")

        bullet = document.add_paragraph()
        bullet.add_run("• ").bold = True
        bullet.add_run(
            "Improved performance using caching."
        )

        document.add_paragraph(
            "AI AGENTS & RESEARCH"
        )

        heading = document.add_paragraph()
        heading.add_run(
            "BrainBee — AI-Powered Learning Platform"
        ).bold = True
        heading.add_run("\t2025")

        bullet = document.add_paragraph()
        bullet.add_run("• ").bold = True
        bullet.add_run(
            "Created educational AI features."
        )

        document.add_paragraph("EDUCATION")
        document.add_paragraph(
            "BS Computer Science — COMSATS University Islamabad"
        )

        document.save(self.source)

        self.profile = {
            "work_items": [
                {
                    "id": "axaon_24ifix",
                    "name": "AXAON — 24iFix Flutter Client",
                    "category": "internship",
                    "organization": "AXAON Software",
                    "role": (
                        "Flutter Developer Intern "
                        "(title needs confirmation)"
                    ),
                    "start_date": "2026-11",
                    "facts": [
                        {
                            "id": "axaon_24ifix_fact_03",
                            "description": (
                                "Worked on customer booking "
                                "and repair-status journeys."
                            ),
                        }
                    ],
                },
                {
                    "id": "recruitflow",
                    "name": (
                        "RecruitFlow — AI-Assisted Recruitment ATS"
                    ),
                    "category": "project",
                    "facts": [
                        {
                            "id": "recruitflow_fact_01",
                            "description": (
                                "Implemented Gmail and PDF "
                                "candidate intake."
                            ),
                        },
                        {
                            "id": "recruitflow_fact_02",
                            "description": (
                                "Built deterministic ATS "
                                "matching and ranking."
                            ),
                        },
                    ],
                },
                {
                    "id": "resume_agent_mvp",
                    "name": (
                        "Evidence-Grounded Resume Agent "
                        "— In Development"
                    ),
                    "category": "project",
                    "start_date": "2026-11",
                    "facts": [
                        {
                            "id": "resume_agent_mvp_fact_01",
                            "description": (
                                "Implemented career models "
                                "and LangGraph nodes."
                            ),
                        }
                    ],
                },
            ]
        }

        self.profile_path.write_text(
            json.dumps(self.profile),
            encoding="utf-8",
        )

        self.resume_doc = {
            "headline": "Junior Full-Stack AI Engineer",
            "summary": (
                "Flutter and Python engineer building "
                "mobile applications with grounded "
                "AI features."
            ),
            "skill_groups": [
                {
                    "title": "Engineering",
                    "skills": [
                        "Flutter",
                        "Python",
                        "Dart",
                    ],
                }
            ],
            "entries": [
                {
                    "work_id": "axaon_24ifix",
                    "section": "experience",
                    "bullets": [
                        {
                            "fact_id": "axaon_24ifix_fact_03",
                            "text": (
                                "Worked on customer booking "
                                "and repair-status journeys."
                            ),
                        }
                    ],
                },
                {
                    "work_id": "recruitflow",
                    "section": "project",
                    "bullets": [
                        {
                            "fact_id": "recruitflow_fact_01",
                            "text": (
                                "Implemented Gmail and PDF "
                                "candidate intake."
                            ),
                        },
                        {
                            "fact_id": "recruitflow_fact_02",
                            "text": (
                                "Built deterministic ATS "
                                "matching and ranking."
                            ),
                        },
                    ],
                },
                {
                    "work_id": "resume_agent_mvp",
                    "section": "project",
                    "bullets": [
                        {
                            "fact_id": "resume_agent_mvp_fact_01",
                            "text": (
                                "Implemented career models "
                                "and LangGraph nodes."
                            ),
                        }
                    ],
                },
            ],
        }

        self.snapshot = {
            "profile_sha256": sha256(
                self.profile_path.read_bytes()
            ).hexdigest(),
            "quality_passed": True,
            "run_status": "rechecked_approved",
            "selected_fact_ids": [
                "axaon_24ifix_fact_03",
                "recruitflow_fact_01",
                "recruitflow_fact_02",
                "resume_agent_mvp_fact_01",
            ],
            "resume_document": self.resume_doc,
            "semantic_recheck": {
                "passed": True,
                "document_sha256": document_hash(
                    self.resume_doc
                ),
            },
        }

        self._write_snapshot()

        self.args = {
            "source_path": self.source,
            "snapshot_path": self.snapshot_path,
            "output_path": self.output,
            "work_ids": [
                "axaon_24ifix",
                "recruitflow",
                "resume_agent_mvp",
            ],
            "experience_anchor": (
                "RECENT MOBILE ENGINEERING EXPERIENCE"
            ),
            "project_anchor": (
                "AI AGENTS & RESEARCH"
            ),
            "experience_style_from": (
                "Mobile App Development Intern — GLOWSIMS"
            ),
            "project_style_from": (
                "BrainBee — AI-Powered Learning Platform"
            ),
        }

    def _write_snapshot(self):
        self.snapshot_path.write_text(
            json.dumps(self.snapshot),
            encoding="utf-8",
        )

    def _run(
        self,
        *,
        dry_run=True,
        **changes,
    ):
        args = {
            **self.args,
            **changes,
        }

        with patch(
            "backend.app.services.safe_entry_inserter."
            "PROFILE_PATH",
            self.profile_path,
        ):
            return insert_missing_approved_entries(
                **args,
                dry_run=dry_run,
            )

    def test_dry_run_leaves_all_files_untouched(self):
        original_hash = sha256(
            self.source.read_bytes()
        ).hexdigest()

        result = self._run()

        self.assertEqual(
            len(result["planned_entries"]),
            3,
        )

        self.assertFalse(
            self.output.exists()
        )

        self.assertEqual(
            sha256(
                self.source.read_bytes()
            ).hexdigest(),
            original_hash,
        )

        self.assertEqual(
            result["inserted_work_ids"],
            [],
        )

    def test_actual_insertion_preserves_source_and_formatting(
        self,
    ):
        original_bytes = self.source.read_bytes()

        result = self._run(dry_run=False)

        self.assertEqual(
            result["inserted_work_ids"],
            self.args["work_ids"],
        )

        self.assertEqual(
            self.source.read_bytes(),
            original_bytes,
        )

        completed = Document(self.output)

        texts = [
            paragraph.text
            for paragraph in completed.paragraphs
        ]

        self.assertEqual(
            sum(
                "RecruitFlow —" in text
                for text in texts
            ),
            1,
        )

        self.assertEqual(
            sum(
                "Evidence-Grounded Resume Agent" in text
                for text in texts
            ),
            1,
        )

        self.assertEqual(
            sum(
                "AXAON Software" in text
                for text in texts
            ),
            1,
        )

        self.assertIn(
            "EDUCATION",
            texts,
        )

        axaon = next(
            paragraph
            for paragraph in completed.paragraphs
            if paragraph.text.startswith(
                "AXAON Software"
            )
        )

        self.assertTrue(
            axaon.runs[0].bold
        )

        self.assertIn(
            "Nov 2026",
            axaon.text,
        )

        index = texts.index(
            axaon.text
        )

        self.assertEqual(
            texts[index + 1],
            (
                "• Worked on customer booking "
                "and repair-status journeys."
            ),
        )

        self.assertTrue(
            any(
                "axaon_24ifix" in warning
                for warning in result["warnings"]
            )
        )

    def test_invalid_approval_rejected(self):
        self.snapshot["quality_passed"] = False
        self._write_snapshot()

        with self.assertRaisesRegex(
            ValueError,
            "semantic approval",
        ):
            self._run()

    def test_changed_document_fingerprint_rejected(self):
        self.snapshot["resume_document"][
            "entries"
        ][0]["bullets"][0]["text"] = (
            "Altered content not covered "
            "by semantic approval."
        )

        self._write_snapshot()

        with self.assertRaisesRegex(
            ValueError,
            "semantic approval",
        ):
            self._run()

    def test_unselected_fact_rejected(self):
        self.snapshot["selected_fact_ids"].remove(
            "recruitflow_fact_02"
        )

        self._write_snapshot()

        with self.assertRaisesRegex(
            ValueError,
            "Unsupported fact",
        ):
            self._run()

    def test_duplicate_requested_work_id_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "unique",
        ):
            self._run(
                work_ids=[
                    "recruitflow",
                    "recruitflow",
                ]
            )

    def test_nonexistent_anchor_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "Expected .*paragraph",
        ):
            self._run(
                project_anchor=(
                    "UNKNOWN PROJECT SECTION"
                )
            )

    def test_output_never_overwritten(self):
        self.output.write_bytes(
            b"retain"
        )

        with self.assertRaises(
            FileExistsError
        ):
            self._run(dry_run=False)

        self.assertEqual(
            self.output.read_bytes(),
            b"retain",
        )

    def test_second_insertion_rejected_as_duplicate(self):
        self._run(dry_run=False)

        with self.assertRaisesRegex(
            ValueError,
            "already exists",
        ):
            self._run(
                source_path=self.output,
                output_path=(
                    self.root / "second.docx"
                ),
                work_ids=["recruitflow"],
            )


if __name__ == "__main__":
    unittest.main()
