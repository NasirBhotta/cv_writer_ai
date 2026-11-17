
import json
import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from backend.app.models.saved_resume_preview import (
    SavedResumeRun,
)
from backend.app.models.template_edit_plan import (
    ParagraphReplacement,
    TemplateEditPlan,
)
from backend.app.models.template_entry_map import (
    DocumentBridgeResult,
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
from backend.app.services.saved_resume_preview import (
    prepare_saved_resume_preview,
    write_saved_resume_preview,
)


class SavedResumePreviewTests(unittest.TestCase):

    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        root = Path(temp.name)

        self.template = root / "cv.docx"
        self.template.write_bytes(
            b"synthetic template for mocked inspection"
        )

        self.profile_path = (
            root / "master_profile.json"
        )

        self.profile_path.write_text(
            '{"example": true}',
            encoding="utf-8",
        )

        self.profile_hash = sha256(
            self.profile_path.read_bytes()
        ).hexdigest()

        self.snapshot_path = root / "saved.json"

        self.payload = {
            "profile_sha256": self.profile_hash,
            "quality_passed": True,
            "selected_fact_ids": ["b1", "b2"],
            "evaluation_feedback": "pass",
            "resume_document": {
                "headline": "Software Engineer",
                "summary": (
                    "Flutter developer with professional "
                    "experience in mobile applications "
                    "and AI engineering."
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
                        "work_id": "brainbee",
                        "section": "project",
                        "bullets": [
                            {
                                "fact_id": "b1",
                                "text": (
                                    "Developed retrieval "
                                    "features."
                                ),
                            },
                            {
                                "fact_id": "b2",
                                "text": (
                                    "Implemented student "
                                    "quizzes."
                                ),
                            },
                        ],
                    }
                ],
            },
        }

        self._save_payload()

        self.report = TemplateReport(
            filename="cv.docx",
            sha256="a" * 64,
            blocks=[
                TemplateBlock(
                    block_id=f"body/{index}",
                    text=text,
                    style_name="Normal",
                )
                for index, text in enumerate([
                    "NAME",
                    "PROFILE",
                    "Previous summary",
                    "PROJECTS",
                    "BrainBee",
                    "• Original 1",
                    "• Original 2",
                ])
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
                    section="projects",
                    heading_id="body/3",
                    heading_text="PROJECTS",
                    content_block_ids=[
                        "body/4",
                        "body/5",
                        "body/6",
                    ],
                ),
            ],
        )

        self.entry_map = TemplateEntryMap(
            template_sha256=self.report.sha256,
            slots=[
                TemplateEntrySlot(
                    section="projects",
                    heading_block_id="body/4",
                    heading_text="BrainBee",
                    bullet_block_ids=[
                        "body/5",
                        "body/6",
                    ],
                    work_id="brainbee",
                    needs_review=False,
                )
            ],
        )

        self.bridged = DocumentBridgeResult(
            plan=TemplateEditPlan(
                template_sha256=self.report.sha256,
                edits=[
                    ParagraphReplacement(
                        block_id="body/5",
                        section="projects",
                        mode="bullet",
                        old_text="• Original 1",
                        new_text=(
                            "Developed retrieval features."
                        ),
                    ),
                    ParagraphReplacement(
                        block_id="body/6",
                        section="projects",
                        mode="bullet",
                        old_text="• Original 2",
                        new_text=(
                            "Implemented student quizzes."
                        ),
                    ),
                ],
            ),
            skipped=[],
        )

    def _save_payload(self):
        self.snapshot_path.write_text(
            json.dumps(self.payload),
            encoding="utf-8",
        )

    def _fake_plan(
        self,
        report,
        mapping,
        *,
        summary=None,
        bullet_replacements=None,
    ):
        edits = []

        if summary is not None:
            edits.append(
                ParagraphReplacement(
                    block_id="body/2",
                    section="summary",
                    mode="plain",
                    old_text="Previous summary",
                    new_text=summary,
                )
            )

        for block_id, new_text in (
            bullet_replacements or {}
        ).items():
            edits.append(
                ParagraphReplacement(
                    block_id=block_id,
                    section="projects",
                    mode="bullet",
                    old_text="• Original 1",
                    new_text=new_text,
                )
            )

        return TemplateEditPlan(
            template_sha256=report.sha256,
            edits=edits,
        )

    def _prepare(self):
        # Mock previously tested services.
        # Test only this new integration layer.
        with (
            patch(
                "backend.app.services.saved_resume_preview."
                "load_profile",
                return_value=SimpleNamespace(
                    work_items=[]
                ),
            ),
            patch(
                "backend.app.services.saved_resume_preview."
                "inspect_template",
                return_value=self.report,
            ),
            patch(
                "backend.app.services.saved_resume_preview."
                "map_template",
                return_value=self.mapping,
            ),
            patch(
                "backend.app.services.saved_resume_preview."
                "map_template_entries",
                return_value=self.entry_map,
            ),
            patch(
                "backend.app.services.saved_resume_preview."
                "build_document_edit_plan",
                return_value=self.bridged,
            ) as bridge,
            patch(
                "backend.app.services.saved_resume_preview."
                "build_resume_edit_plan",
            ) as planner,
        ):
            planner.side_effect = self._fake_plan

            prepared = prepare_saved_resume_preview(
                self.template,
                self.snapshot_path,
                profile_path=self.profile_path,
            )

            return prepared, bridge, planner

    def test_saved_run_is_valid(self):
        run = SavedResumeRun.model_validate(
            self.payload
        )

        self.assertEqual(
            run.resume_document.entries[0].work_id,
            "brainbee",
        )

        self.assertEqual(
            run.selected_fact_ids,
            ["b1", "b2"],
        )

    def test_duplicate_selected_facts_rejected(self):
        self.payload["selected_fact_ids"] = [
            "b1",
            "b1",
        ]

        with self.assertRaisesRegex(
            ValidationError,
            "duplicate",
        ):
            SavedResumeRun.model_validate(
                self.payload
            )

    def test_profile_hash_mismatch_rejected(self):
        self.profile_path.write_text(
            "changed",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            ValueError,
            "Master profile changed",
        ):
            prepare_saved_resume_preview(
                self.template,
                self.snapshot_path,
                profile_path=self.profile_path,
            )

    def test_summary_and_bullets_combined_without_llm(self):
        prepared, bridge, planner = self._prepare()

        self.assertEqual(
            prepared.manifest.planned_block_ids,
            [
                "body/2",
                "body/5",
                "body/6",
            ],
        )

        self.assertEqual(
            prepared.manifest.updated_work_ids,
            ["brainbee"],
        )

        self.assertTrue(
            prepared.manifest.summary_included
        )

        self.assertTrue(
            prepared.manifest.preview_only
        )

        self.assertEqual(
            bridge.call_args.kwargs[
                "allowed_fact_ids"
            ],
            {"b1", "b2"},
        )

        self.assertTrue(
            bridge.call_args.kwargs[
                "allow_partial"
            ]
        )

        self.assertEqual(
            planner.call_args.kwargs[
                "bullet_replacements"
            ],
            {
                "body/5": (
                    "Developed retrieval features."
                ),
                "body/6": (
                    "Implemented student quizzes."
                ),
            },
        )

    def test_failed_evaluation_blocks_writing(self):
        self.payload["quality_passed"] = False
        self._save_payload()

        prepared, _, _ = self._prepare()

        self.assertFalse(
            prepared.manifest.quality_passed
        )

        with self.assertRaisesRegex(
            ValueError,
            "did not pass",
        ):
            write_saved_resume_preview(
                prepared,
                "unused.docx",
            )

    def test_passed_evaluation_can_write_preview(self):
        prepared, _, _ = self._prepare()

        output = (
            self.template.parent / "preview.docx"
        )

        with patch(
            "backend.app.services.saved_resume_preview."
            "apply_template_edit_plan",
            return_value=output,
        ) as editor:
            result = write_saved_resume_preview(
                prepared,
                output,
            )

        self.assertEqual(result, output)

        self.assertEqual(
            editor.call_args.args[0],
            str(self.template),
        )

        self.assertEqual(
            editor.call_args.args[1],
            output,
        )

    def test_partial_matching_warns_about_unchanged_entries(self):
        self.entry_map.slots.append(
            TemplateEntrySlot(
                section="projects",
                heading_block_id="body/99",
                heading_text="Unmatched project",
                bullet_block_ids=["body/100"],
                work_id=None,
                needs_review=True,
            )
        )

        self.bridged.skipped.append(
            "unmatched: no unique approved template entry"
        )

        prepared, _, _ = self._prepare()

        self.assertEqual(
            len(
                prepared.manifest
                .unchanged_template_entries
            ),
            1,
        )

        self.assertEqual(
            len(
                prepared.manifest.skipped_entries
            ),
            1,
        )

        self.assertTrue(
            any(
                "NOT a final" in warning
                for warning in (
                    prepared.manifest.warnings
                )
            )
        )

    def test_no_safe_edits_has_no_plan(self):
        self.mapping.regions[0].needs_review = True
        self.bridged.plan = None

        prepared, _, planner = self._prepare()

        self.assertIsNone(prepared.plan)

        self.assertFalse(
            prepared.manifest.summary_included
        )

        planner.assert_not_called()

        with self.assertRaisesRegex(
            ValueError,
            "No safe DOCX edits",
        ):
            write_saved_resume_preview(
                prepared,
                "unused.docx",
            )

    def test_missing_snapshot(self):
        self.snapshot_path.unlink()

        with self.assertRaises(
            FileNotFoundError
        ):
            prepare_saved_resume_preview(
                self.template,
                self.snapshot_path,
                profile_path=self.profile_path,
            )


if __name__ == "__main__":
    unittest.main()
