
import json
import unittest

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from docx import Document

from backend.app.services.safe_entry_removal import (
    plan_entry_removal,
    apply_entry_removal,
)
from backend.app.services.snapshot_semantic_recheck import (
    document_hash,
)


class SelectiveRemovalTests(unittest.TestCase):

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        root = Path(temp.name)

        self.source = root / "base.docx"
        self.output = root / "filtered.docx"
        self.profile = root / "profile.json"
        self.snapshot = root / "approved.json"

        doc = Document()

        doc.add_paragraph("NASIR SHAHZAD")
        doc.add_paragraph("SELECTED PROJECTS")

        for title, bullet in [
            (
                "BrainBee — AI Platform",
                "Verified educational AI features.",
            ),
            (
                "Old Unselected Demo",
                "Outdated demo project information.",
            ),
            (
                "RecruitFlow — ATS",
                "Built deterministic recruitment matching.",
            ),
        ]:
            heading = doc.add_paragraph()
            heading.add_run(title).bold = True

            paragraph = doc.add_paragraph()
            paragraph.add_run("• ").bold = True
            paragraph.add_run(bullet)

        doc.add_paragraph("EDUCATION")
        doc.add_paragraph("BS Computer Science")

        doc.save(self.source)

        profile = {
            "work_items": [
                {
                    "id": "brainbee",
                    "name": "BrainBee — AI Platform",
                    "category": "project",
                },
                {
                    "id": "recruitflow",
                    "name": "RecruitFlow — ATS",
                    "category": "project",
                },
            ]
        }

        self.profile.write_text(
            json.dumps(profile),
            encoding="utf-8",
        )

        resume = {
            "headline": "Software Engineer",
            "summary": (
                "Software engineer experienced "
                "in Flutter and AI application design."
            ),
            "skill_groups": [
                {
                    "title": "Engineering",
                    "skills": ["Flutter"],
                }
            ],
            "entries": [
                {
                    "work_id": "brainbee",
                    "section": "project",
                    "bullets": [
                        {
                            "fact_id": "a",
                            "text": (
                                "Verified educational "
                                "AI features."
                            ),
                        }
                    ],
                },
                {
                    "work_id": "recruitflow",
                    "section": "project",
                    "bullets": [
                        {
                            "fact_id": "b",
                            "text": (
                                "Built deterministic "
                                "recruitment matching."
                            ),
                        }
                    ],
                },
            ],
        }

        snapshot = {
            "resume_document": resume,
            "quality_passed": True,
            "run_status": "rechecked_approved",
            "semantic_recheck": {
                "passed": True,
                "document_sha256": document_hash(
                    resume
                ),
            },
            "selected_fact_ids": [
                "a",
                "b",
            ],
            "profile_sha256": sha256(
                self.profile.read_bytes()
            ).hexdigest(),
        }

        self.snapshot.write_text(
            json.dumps(snapshot),
            encoding="utf-8",
        )

        self.kwargs = {
            "source_path": self.source,
            "snapshot_path": self.snapshot,
            "section_start": "SELECTED PROJECTS",
            "section_end": "EDUCATION",
            "remove_titles": [
                "Old Unselected Demo"
            ],
        }

    def call(self, fn, **kwargs):
        with patch(
            "backend.app.services.safe_entry_removal."
            "PROFILE_PATH",
            self.profile,
        ):
            return fn(
                **{
                    **self.kwargs,
                    **kwargs,
                }
            )

    def test_dry_run_does_not_write(self):
        plan = self.call(
            plan_entry_removal
        )

        self.assertTrue(plan.can_apply)

        self.assertEqual(
            plan.targets[0].bullet_indices,
            [5],
        )

        self.assertFalse(
            self.output.exists()
        )

    def test_real_remove_preserves_all_approved(
        self,
    ):
        original = self.source.read_bytes()

        result = self.call(
            apply_entry_removal,
            output_path=self.output,
        )

        self.assertTrue(
            result["approved_bullets_preserved"]
        )

        self.assertEqual(
            self.source.read_bytes(),
            original,
        )

        texts = [
            paragraph.text
            for paragraph in Document(
                self.output
            ).paragraphs
        ]

        self.assertNotIn(
            "Old Unselected Demo",
            texts,
        )

        self.assertNotIn(
            "• Outdated demo project information.",
            texts,
        )

        self.assertIn(
            "• Verified educational AI features.",
            texts,
        )

        self.assertIn(
            "• Built deterministic recruitment matching.",
            texts,
        )

        self.assertIn(
            "EDUCATION",
            texts,
        )

    def test_approved_heading_blocked(self):
        plan = self.call(
            plan_entry_removal,
            remove_titles=[
                "BrainBee — AI Platform"
            ],
        )

        self.assertFalse(
            plan.can_apply
        )

        self.assertIn(
            "approved",
            plan.warnings[0].lower(),
        )

    def test_missing_heading_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "must occur once",
        ):
            self.call(
                plan_entry_removal,
                remove_titles=[
                    "Unknown Project"
                ],
            )

    def test_approval_mismatch_rejected(self):
        data = json.loads(
            self.snapshot.read_text()
        )

        data["semantic_recheck"][
            "document_sha256"
        ] = "bad"

        self.snapshot.write_text(
            json.dumps(data)
        )

        with self.assertRaisesRegex(
            ValueError,
            "semantic approval",
        ):
            self.call(
                plan_entry_removal
            )

    def test_missing_approved_bullet_rejected(self):
        doc = Document(
            self.source
        )

        for paragraph in doc.paragraphs:
            if (
                "Verified educational"
                in paragraph.text
            ):
                paragraph.text = (
                    "• Completely different claim."
                )

        doc.save(self.source)

        with self.assertRaisesRegex(
            ValueError,
            "missing approved",
        ):
            self.call(
                plan_entry_removal
            )

    def test_embedded_link_rejected(self):
        doc = Document(
            self.source
        )

        target = next(
            paragraph
            for paragraph in doc.paragraphs
            if paragraph.text
            == "Old Unselected Demo"
        )

        from docx.oxml import OxmlElement

        target._p.append(
            OxmlElement("w:hyperlink")
        )

        doc.save(self.source)

        plan = self.call(
            plan_entry_removal
        )

        self.assertFalse(
            plan.can_apply
        )

    def test_ambiguous_content_rejected(self):
        doc = Document(
            self.source
        )

        for paragraph in doc.paragraphs:
            if paragraph.text == (
                "• Outdated demo project information."
            ):
                paragraph.insert_paragraph_before(
                    "EXTRA NOTE"
                )
                break

        doc.save(self.source)

        plan = self.call(
            plan_entry_removal
        )

        self.assertFalse(
            plan.can_apply
        )

        self.assertIn(
            "No contiguous",
            plan.warnings[0],
        )

    def test_table_between_heading_and_bullet_rejected(
        self,
    ):
        doc = Document(
            self.source
        )

        target = next(
            paragraph
            for paragraph in doc.paragraphs
            if paragraph.text
            == "Old Unselected Demo"
        )

        from docx.oxml import OxmlElement

        target._p.addnext(
            OxmlElement("w:tbl")
        )

        doc.save(self.source)

        plan = self.call(
            plan_entry_removal
        )

        self.assertFalse(
            plan.can_apply
        )

        self.assertIn(
            "separated",
            plan.warnings[0],
        )

    def test_does_not_overwrite(self):
        self.output.write_bytes(
            b"existing"
        )

        with self.assertRaises(
            FileExistsError
        ):
            self.call(
                apply_entry_removal,
                output_path=self.output,
            )

        self.assertEqual(
            self.output.read_bytes(),
            b"existing",
        )

    def test_wrong_section_order_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "end must appear after",
        ):
            self.call(
                plan_entry_removal,
                section_start="EDUCATION",
                section_end="SELECTED PROJECTS",
            )


if __name__ == "__main__":
    unittest.main()
