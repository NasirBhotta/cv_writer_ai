
"""Offline orchestrator tests: mocked services, real temporary files."""

import hashlib
import json
import shutil
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from pydantic import BaseModel, Field

from backend.app.models.page_layout_policy import (
    PageRequirements,
)

from backend.app.models.resume_pipeline_result import (
    InsertionChoice,
    RemovalChoice,
    ResumeAssemblyRequest,
)

from backend.app.services import (
    resume_pipeline_orchestrator as service,
)


class FakeEntry(BaseModel):
    work_id: str = "work_1"
    status: str = "pass"


class FakeTemplateItem(BaseModel):
    heading: str


class FakeFact(BaseModel):
    fact_id: str


class FakeContent(BaseModel):
    approved_content_complete: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    entries: list[FakeEntry] = Field(
        default_factory=lambda: [FakeEntry()]
    )
    retained_template_entries: list[
        FakeTemplateItem
    ] = Field(default_factory=list)
    omitted_selected_facts: list[FakeFact] = Field(
        default_factory=list
    )


class FakeLayout(BaseModel):
    automated_checks_passed: bool = True
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    page_images: list[str] = Field(default_factory=list)


class FakeRemovalPlan(BaseModel):
    can_apply: bool = True


class PipelineTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.root = Path(self.temp.name)

        self.profile = self.root / "master.json"
        self.template = self.root / "user.docx"
        self.snapshot = self.root / "approved.json"

        self.profile.write_text(
            '{"work_items": []}',
            encoding="utf-8",
        )

        self.template.write_bytes(
            b"untouched user template fixture"
        )

        self.document = {
            "entries": [
                {"work_id": "work_1"}
            ]
        }

        self.fake_hash = (
            lambda doc: (
                "doc-proof"
                if doc == self.document
                else "different"
            )
        )

        self.approval = {
            "quality_passed": True,
            "run_status": "rechecked_approved",
            "resume_document": self.document,
            "profile_sha256": hashlib.sha256(
                self.profile.read_bytes()
            ).hexdigest(),
            "semantic_recheck": {
                "passed": True,
                "document_sha256": "doc-proof",
            },
        }

        self.save_snapshot()

        self.content = FakeContent()
        self.layout = FakeLayout()
        self.calls = []

        self.patch(
            service,
            "PROFILE_PATH",
            self.profile,
        )

        self.patch(
            service,
            "document_hash",
            self.fake_hash,
        )

        self.patch(
            service,
            "load_candidate_for_recheck",
            lambda *_: ({}, {}),
        )

        self.patch(
            service,
            "write_dynamic_resume_preview",
            self.preview,
        )

        self.patch(
            service,
            "audit_resume_content",
            lambda **_: self.content,
        )

        self.patch(
            service,
            "export_docx_to_pdf",
            self.pdf,
        )

        self.patch(
            service,
            "audit_resume_layout",
            lambda **_: self.layout,
        )

    def patch(self, obj, name, value):
        patcher = patch.object(obj, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save_snapshot(self):
        self.snapshot.write_text(
            json.dumps(self.approval),
            encoding="utf-8",
        )

    def request(self, **kwargs):
        defaults = dict(
            template_path=self.template,
            approved_snapshot_path=self.snapshot,
            profile_path=self.profile,
            output_root=self.root / "builds",
            job_description=(
                "Full stack Python AI engineer"
            ),
        )

        defaults.update(kwargs)
        return ResumeAssemblyRequest(**defaults)

    def preview(
        self,
        template,
        _snapshot,
        output,
    ):
        self.calls.append("preview")
        shutil.copyfile(template, output)
        return {"skipped": []}

    def pdf(self, _source, target, **_):
        self.calls.append("pdf")

        target = Path(target)

        target.write_bytes(
            b"synthetic PDF for mocked audit"
        )

        return target

    def test_successful_automated_run_requires_visual_review(
        self,
    ):
        result = service.assemble_resume(
            self.request()
        )

        self.assertEqual(
            result.status,
            "needs_review",
        )
        self.assertTrue(
            result.automated_checks_passed
        )
        self.assertFalse(
            result.ready_for_export
        )
        self.assertIn(
            "assembled_preview_pdf",
            result.artifacts,
        )
        self.assertTrue(
            Path(
                result.artifacts["report"]
            ).is_file()
        )

    def test_source_files_remain_unchanged(self):
        paths = (
            self.template,
            self.profile,
            self.snapshot,
        )

        baseline = [
            path.read_bytes()
            for path in paths
        ]

        service.assemble_resume(
            self.request()
        )

        self.assertEqual(
            baseline,
            [
                path.read_bytes()
                for path in paths
            ],
        )

    def test_custom_profile_rejected_before_preview(
        self,
    ):
        other = self.root / "other.json"

        other.write_text(
            "{}",
            encoding="utf-8",
        )

        result = service.assemble_resume(
            self.request(
                profile_path=other
            )
        )

        self.assertEqual(
            result.status,
            "failed",
        )

        self.assertIn(
            "Custom profiles",
            " ".join(result.errors),
        )

        self.assertNotIn(
            "preview",
            self.calls,
        )

    def test_rejected_snapshot_never_renders(self):
        self.approval[
            "semantic_recheck"
        ]["passed"] = False

        self.save_snapshot()

        result = service.assemble_resume(
            self.request()
        )

        self.assertEqual(
            result.status,
            "failed",
        )

        self.assertNotIn(
            "preview",
            self.calls,
        )

    def test_profile_hash_mismatch_rejected(self):
        self.profile.write_text(
            "changed",
            encoding="utf-8",
        )

        result = service.assemble_resume(
            self.request()
        )

        self.assertEqual(
            result.status,
            "failed",
        )

        self.assertNotIn(
            "preview",
            self.calls,
        )

    def test_snapshot_document_hash_mismatch_rejected(
        self,
    ):
        self.approval[
            "semantic_recheck"
        ]["document_sha256"] = "wrong"

        self.save_snapshot()

        result = service.assemble_resume(
            self.request()
        )

        self.assertEqual(
            result.status,
            "failed",
        )

    def test_policy_conflict_stops_before_render(
        self,
    ):
        result = service.assemble_resume(
            self.request(
                pages=PageRequirements(
                    user_exact_pages=3,
                    employer_max_pages=2,
                )
            )
        )

        self.assertEqual(
            result.status,
            "needs_review",
        )

        self.assertFalse(
            result.automated_checks_passed
        )

        self.assertNotIn(
            "preview",
            self.calls,
        )

    def test_content_missing_entry_remains_unapproved(
        self,
    ):
        self.content.entries = [
            FakeEntry(status="fail")
        ]

        self.content.approved_content_complete = False

        result = service.assemble_resume(
            self.request()
        )

        self.assertFalse(
            result.automated_checks_passed
        )

        self.assertEqual(
            result.unresolved_work_ids,
            ["work_1"],
        )

    def test_retained_template_entry_requires_review(
        self,
    ):
        self.content.retained_template_entries = [
            FakeTemplateItem(
                heading="Old Project"
            )
        ]

        result = service.assemble_resume(
            self.request()
        )

        self.assertEqual(
            result.retained_template_entries,
            ["Old Project"],
        )

        self.assertFalse(
            result.ready_for_export
        )

    def test_omitted_selected_fact_flagged(self):
        self.content.omitted_selected_facts = [
            FakeFact(fact_id="f1")
        ]

        result = service.assemble_resume(
            self.request()
        )

        self.assertEqual(
            result.omitted_selected_fact_ids,
            ["f1"],
        )

        self.assertTrue(
            result.review_reasons
        )

    def insertion_choice(self, work_ids=None):
        return InsertionChoice(
            work_ids=work_ids or ["work_1"],
            experience_anchor="Experience",
            project_anchor="Projects",
            experience_style_from="Role",
            project_style_from="Project",
        )

    def test_nonapproved_insertion_rejected(self):
        result = service.assemble_resume(
            self.request(
                insertion=self.insertion_choice(
                    ["other"]
                )
            )
        )

        self.assertEqual(
            result.status,
            "failed",
        )

        self.assertIn(
            "non-approved",
            " ".join(result.errors),
        )

    def test_insertion_requires_dry_run_first(
        self,
    ):
        def fake_inserter(**kwargs):
            self.calls.append(
                "insert-dry"
                if kwargs["dry_run"]
                else "insert-apply"
            )

            if not kwargs["dry_run"]:
                shutil.copyfile(
                    kwargs["source_path"],
                    kwargs["output_path"],
                )

            return {
                "dry_run": kwargs["dry_run"]
            }

        self.patch(
            service,
            "insert_missing_approved_entries",
            fake_inserter,
        )

        result = service.assemble_resume(
            self.request(
                insertion=self.insertion_choice()
            )
        )

        self.assertEqual(
            result.status,
            "needs_review",
        )

        self.assertEqual(
            self.calls[:3],
            [
                "preview",
                "insert-dry",
                "insert-apply",
            ],
        )

    def test_insertion_review_blocks_apply(
        self,
    ):
        self.patch(
            service,
            "insert_missing_approved_entries",
            lambda **_: {
                "requires_review": True
            },
        )

        result = service.assemble_resume(
            self.request(
                insertion=self.insertion_choice()
            )
        )

        self.assertEqual(
            result.status,
            "needs_review",
        )

        self.assertNotIn(
            "assembled_preview_pdf",
            result.artifacts,
        )

    def removal_choice(self):
        return RemovalChoice(
            titles=["Old Project"],
            section_start="Projects",
            section_end="Education",
        )

    def test_unsafe_removal_does_not_apply(self):
        self.patch(
            service,
            "plan_entry_removal",
            lambda **_: FakeRemovalPlan(
                can_apply=False
            ),
        )

        self.patch(
            service,
            "apply_entry_removal",
            lambda **_: self.fail(
                "Removal must not run"
            ),
        )

        result = service.assemble_resume(
            self.request(
                removal=self.removal_choice()
            )
        )

        self.assertEqual(
            result.status,
            "needs_review",
        )

        self.assertTrue(
            result.review_reasons
        )

    def test_explicit_safe_removal_applies(self):
        self.patch(
            service,
            "plan_entry_removal",
            lambda **_: FakeRemovalPlan(),
        )

        def apply(**kwargs):
            self.calls.append(
                "remove-apply"
            )

            shutil.copyfile(
                kwargs["source_path"],
                kwargs["output_path"],
            )

        self.patch(
            service,
            "apply_entry_removal",
            apply,
        )

        result = service.assemble_resume(
            self.request(
                removal=self.removal_choice()
            )
        )

        self.assertIn(
            "remove-apply",
            self.calls,
        )

        self.assertIn(
            "removed_docx",
            result.artifacts,
        )

    def test_template_only_is_never_auto_removed(
        self,
    ):
        self.content.retained_template_entries = [
            FakeTemplateItem(
                heading="Old Project"
            )
        ]

        self.patch(
            service,
            "apply_entry_removal",
            lambda **_: self.fail(
                "Unexpected deletion"
            ),
        )

        service.assemble_resume(
            self.request()
        )

    def test_converter_failure_is_recorded(self):
        def fail_converter(*_, **__):
            raise RuntimeError(
                "Word is unavailable"
            )

        self.patch(
            service,
            "export_docx_to_pdf",
            fail_converter,
        )

        result = service.assemble_resume(
            self.request()
        )

        self.assertEqual(
            result.status,
            "failed",
        )

        self.assertIn(
            "Word is unavailable",
            " ".join(result.errors),
        )

    def test_layout_violation_prevents_automated_pass(
        self,
    ):
        self.layout.automated_checks_passed = False

        self.layout.errors = [
            "3 pages exceeds maximum 2"
        ]

        result = service.assemble_resume(
            self.request()
        )

        self.assertFalse(
            result.automated_checks_passed
        )

        self.assertFalse(
            result.ready_for_export
        )

    def test_repeated_runs_are_isolated(self):
        first = service.assemble_resume(
            self.request()
        )

        second = service.assemble_resume(
            self.request()
        )

        self.assertNotEqual(
            first.run_directory,
            second.run_directory,
        )


if __name__ == "__main__":
    unittest.main()
