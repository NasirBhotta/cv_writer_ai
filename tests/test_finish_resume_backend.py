
import json
import unittest

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from docx import Document

from backend.app.models.template_entry_map import (
    TemplateEntryMap,
    TemplateEntrySlot,
)
from backend.app.models.template_mapping import (
    TemplateMapping,
    TemplateRegion,
)
from backend.app.models.template_report import (
    TemplateBlock,
    TemplateReport,
)
from backend.app.services.profile_store import (
    PROFILE_PATH,
)
from backend.app.services.dynamic_resume_preview import (
    write_dynamic_resume_preview,
)
from backend.app.services.snapshot_semantic_recheck import (
    document_hash,
    semantic_recheck_and_save,
)


class FinishBackendTests(unittest.TestCase):

    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)

        self.root = Path(folder.name)
        self.source = self.root / "cv.docx"
        self.output = self.root / "preview.docx"

        doc = Document()

        for text in (
            "TEST CANDIDATE",
            "PROFILE",
            "Old summary text",
            "WORK EXPERIENCE",
            "GLOWSIMS — Mobile App Development Intern",
        ):
            doc.add_paragraph(text)

        for text in (
            "Old API fact",
            "Old dashboard fact",
            "Old attendance fact",
        ):
            p = doc.add_paragraph()
            p.add_run("• ").bold = True
            p.add_run(text)

        doc.add_paragraph("PROJECTS")

        doc.add_paragraph(
            "BrainBee — AI-Powered Learning Platform"
        )

        for text in (
            "Old retrieval",
            "Old quizzes",
        ):
            p = doc.add_paragraph()
            p.add_run("• ").bold = True
            p.add_run(text)

        doc.save(self.source)

        self.report = TemplateReport(
            filename="cv.docx",
            sha256=sha256(
                self.source.read_bytes()
            ).hexdigest(),
            blocks=[
                TemplateBlock(
                    block_id=f"body/{i}",
                    text=p.text,
                    style_name="Normal",
                )
                for i, p in enumerate(doc.paragraphs)
                if p.text
            ],
            section_hints=[],
            layouts=[],
        )

        self.mapping = TemplateMapping(
            template_sha256=self.report.sha256,
            regions=[
                TemplateRegion(
                    section="summary",
                    heading_id="body/1",
                    heading_text="PROFILE",
                    content_block_ids=["body/2"],
                ),
                TemplateRegion(
                    section="experience",
                    heading_id="body/3",
                    heading_text="WORK EXPERIENCE",
                    content_block_ids=[
                        "body/4", "body/5",
                        "body/6", "body/7",
                    ],
                ),
                TemplateRegion(
                    section="projects",
                    heading_id="body/8",
                    heading_text="PROJECTS",
                    content_block_ids=[
                        "body/9", "body/10", "body/11",
                    ],
                ),
            ],
        )

        self.entry_map = TemplateEntryMap(
            template_sha256=self.report.sha256,
            slots=[
                TemplateEntrySlot(
                    section="experience",
                    heading_block_id="body/4",
                    heading_text="GLOWSIMS internship",
                    bullet_block_ids=[
                        "body/5",
                        "body/6",
                        "body/7",
                    ],
                    work_id="glowsims_intern",
                ),
                TemplateEntrySlot(
                    section="projects",
                    heading_block_id="body/9",
                    heading_text="BrainBee",
                    bullet_block_ids=[
                        "body/10",
                        "body/11",
                    ],
                    work_id="brainbee",
                ),
            ],
        )

        self.snapshot = {
            "quality_passed": True,
            "run_status": "rechecked_approved",
            "profile_sha256": sha256(
                PROFILE_PATH.read_bytes()
            ).hexdigest(),
            "selected_fact_ids": [
                "glowsims_intern_fact_01",
                "glowsims_intern_fact_03",
                "brainbee_rag",
                "brainbee_flutter",
                "brainbee_fact_03",
            ],
            "resume_document": {
                "headline": "Full-Stack AI Engineer",
                "summary": (
                    "Flutter engineer building mobile "
                    "applications and grounded AI "
                    "features for real users."
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
                        "work_id": "glowsims_intern",
                        "section": "experience",
                        "bullets": [
                            {
                                "fact_id": "glowsims_intern_fact_01",
                                "text": (
                                    "Improved database query "
                                    "performance for the LMS APIs."
                                ),
                            },
                            {
                                "fact_id": "glowsims_intern_fact_03",
                                "text": (
                                    "Improved Talib dashboards "
                                    "using caching and pagination."
                                ),
                            },
                        ],
                    },
                    {
                        "work_id": "brainbee",
                        "section": "project",
                        "bullets": [
                            {
                                "fact_id": "brainbee_rag",
                                "text": (
                                    "Implemented textbook retrieval "
                                    "with embeddings and FAISS."
                                ),
                            },
                            {
                                "fact_id": "brainbee_flutter",
                                "text": (
                                    "Developed Flutter learning "
                                    "interfaces connected to "
                                    "backend APIs."
                                ),
                            },
                            {
                                "fact_id": "brainbee_fact_03",
                                "text": (
                                    "Created AI-assisted quizzes, "
                                    "flashcards, and summaries."
                                ),
                            },
                        ],
                    },
                ],
            },
        }

        self.snapshot["semantic_recheck"] = {
            "passed": True,
            "document_sha256": document_hash(
                self.snapshot["resume_document"]
            ),
        }

        self.snapshot_file = (
            self.root / "approved.json"
        )

        self._save_snapshot()

    def _save_snapshot(self):
        self.snapshot_file.write_text(
            json.dumps(self.snapshot),
            encoding="utf-8",
        )

    def _render(self):
        with (
            patch(
                "backend.app.services.dynamic_resume_preview."
                "inspect_template",
                return_value=self.report,
            ),
            patch(
                "backend.app.services.dynamic_resume_preview."
                "map_template",
                return_value=self.mapping,
            ),
            patch(
                "backend.app.services.dynamic_resume_preview."
                "map_template_entries",
                return_value=self.entry_map,
            ),
        ):
            return write_dynamic_resume_preview(
                self.source,
                self.snapshot_file,
                self.output,
            )

    def test_dynamic_bullet_add_remove(self):
        before = self.source.read_bytes()

        result = self._render()

        self.assertEqual(
            result["bullets_inserted"], 1
        )

        self.assertEqual(
            result["bullets_removed"], 1
        )

        self.assertEqual(
            self.source.read_bytes(),
            before,
        )

        text = "\n".join(
            p.text
            for p in Document(self.output).paragraphs
        )

        self.assertIn(
            "Created AI-assisted quizzes",
            text,
        )

        self.assertNotIn(
            "Old attendance fact",
            text,
        )

    def test_modified_approved_snapshot_blocked(self):
        self.snapshot["resume_document"][
            "summary"
        ] = (
            "A different summary after approval, "
            "requiring new evaluation."
        )

        self._save_snapshot()

        with self.assertRaisesRegex(
            ValueError,
            "changed after semantic recheck",
        ):
            self._render()

        self.assertFalse(
            self.output.exists()
        )

    def test_failed_semantic_status_blocked(self):
        self.snapshot["quality_passed"] = False

        self._save_snapshot()

        with self.assertRaisesRegex(
            ValueError,
            "successful semantic recheck",
        ):
            self._render()

    def test_semantic_recheck_one_call(self):
        candidate = (
            self.root / "candidate.json"
        )

        approved = (
            self.root / "approved_new.json"
        )

        candidate.write_text(
            json.dumps({
                "resume_document": {
                    "example": "value"
                }
            }),
            encoding="utf-8",
        )

        payload = {
            "headline": "Engineer",
            "summary": "Example summary",
            "skills_in_profile": [],
            "selected_sources": [],
            "bullets": [
                {
                    "work_id": "x",
                    "fact_id": "f1",
                    "source_fact": "Original statement",
                    "candidate_bullet": (
                        "Original statement"
                    ),
                }
            ],
        }

        with (
            patch(
                "backend.app.services."
                "snapshot_semantic_recheck."
                "load_candidate_for_recheck",
                return_value=(
                    json.loads(candidate.read_text()),
                    payload,
                ),
            ),
            patch(
                "backend.app.services.llm_client."
                "LLMClient"
            ) as client,
        ):
            client.return_value.generate.return_value = (
                json.dumps({
                    "passed": True,
                    "checked_fact_ids": ["f1"],
                    "issues": [],
                })
            )

            result = semantic_recheck_and_save(
                candidate,
                approved,
            )

            client.return_value.generate.assert_called_once()

        self.assertTrue(
            result["passed"]
        )

        self.assertTrue(
            approved.exists()
        )

        saved = json.loads(
            approved.read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            saved["run_status"],
            "rechecked_approved",
        )


if __name__ == "__main__":
    unittest.main()
