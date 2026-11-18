
"""Fresh mode integration tests; preserve the existing snapshot-mode suite.

All LLM, DOCX, PDF and graph side effects are mocked. Only temporary files
are created, and the profile/template are never mutated by a passing run.
"""

import hashlib
import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from backend.app.models.resume_pipeline_result import (
    FreshResumeRequest,
    InsertionChoice,
    ResumePipelineResult,
)
from backend.app.services import resume_pipeline_orchestrator as svc


class FreshIntegrationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.profile = self.root / "master.json"
        self.template = self.root / "sample.docx"
        self.profile.write_text('{"work_items": []}', encoding="utf-8")
        self.template.write_bytes(b"original template")
        self.original_profile = self.profile.read_bytes()
        self.original_template = self.template.read_bytes()
        self.calls = []
        self.verdict_passes = True
        self.selected = ["work_1"]
        self.state = {
            "quality_passed": True,
            "selected_fact_ids": ["fact_1"],
            "resume_document": {"entries": [{"work_id": "work_1"}]},
            "revision_count": 1,
            "evaluation_feedback": "Passed",
        }
        self.assembly_request = None

        self.mock(svc, "PROFILE_PATH", self.profile)
        self.mock(svc, "_graph_invoke", self.graph)
        self.mock(svc, "load_candidate_for_recheck", self.grounding)
        self.mock(svc, "semantic_recheck_and_save", self.semantic)
        self.mock(svc, "document_hash", lambda _: "document-digest")
        self.mock(svc, "assemble_resume", self.assembly)

    def mock(self, obj, name, value):
        hook = patch.object(obj, name, value)
        hook.start()
        self.addCleanup(hook.stop)

    def request(self, **changes):
        values = dict(
            template_path=self.template,
            job_description=(
                "Hiring a Junior Full-Stack AI Engineer with Python and RAG."
            ),
            target_role="hybrid",
            max_pages=2,
            output_root=self.root / "fresh",
        )
        values.update(changes)
        return FreshResumeRequest(**values)

    def graph(self, inputs):
        self.calls.append(("graph", inputs))
        return self.state

    def grounding(self, candidate):
        self.calls.append(("grounding", str(candidate)))
        snapshot = json.loads(
            Path(candidate).read_text(encoding="utf-8")
        )
        self.assertEqual(snapshot["run_status"], "completed")
        self.assertEqual(
            snapshot["profile_sha256"],
            hashlib.sha256(self.profile.read_bytes()).hexdigest(),
        )
        return snapshot, {}

    def semantic(self, candidate, output):
        self.calls.append(("semantic", str(candidate)))
        snapshot = json.loads(
            Path(candidate).read_text(encoding="utf-8")
        )
        snapshot["quality_passed"] = self.verdict_passes
        snapshot["run_status"] = (
            "rechecked_approved" if self.verdict_passes
            else "rechecked_rejected"
        )
        snapshot["semantic_recheck"] = {
            "passed": self.verdict_passes,
            "document_sha256": "document-digest",
            "checked_fact_ids": ["fact_1"],
        }
        Path(output).write_text(json.dumps(snapshot), encoding="utf-8")
        return {
            "passed": self.verdict_passes,
            "issues": [] if self.verdict_passes else ["Unproven metric"],
        }

    def assembly(self, request):
        self.calls.append(("assembly", str(request.approved_snapshot_path)))
        self.assembly_request = request
        directory = request.output_root / "mocked"
        directory.mkdir(parents=True)
        docx = directory / "tailored.docx"
        pdf = directory / "tailored.pdf"
        docx.write_bytes(b"docx")
        pdf.write_bytes(b"pdf")
        return ResumePipelineResult(
            run_id="nested",
            run_directory=str(directory),
            status="needs_review",
            artifacts={
                "report": str(directory / "pipeline_report.json"),
                "assembled_preview_docx": str(docx),
                "assembled_preview_pdf": str(pdf),
            },
            content_automated_passed=True,
            layout_automated_passed=True,
            automated_checks_passed=True,
            review_reasons=["Human review pending"],
        )

    def test_fresh_jd_calls_existing_components_in_order(self):
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual(
            [name for name, _ in self.calls],
            ["graph", "grounding", "semantic", "assembly"],
        )
        self.assertTrue(result.graph_quality_passed)
        self.assertTrue(result.semantic_passed)
        self.assertTrue(result.automated_checks_passed)
        self.assertEqual(result.status, "needs_review")
        self.assertFalse(result.ready_for_export)
        self.assertTrue(Path(result.artifacts["report"]).is_file())
        self.assertTrue(Path(result.artifacts["assembled_preview_pdf"]).is_file())

    def test_graph_inputs_preserve_jd_role_and_pages(self):
        request = self.request(target_role="ai", max_pages=3)
        svc.generate_resume_from_jd(request)
        self.assertEqual(
            self.calls[0][1],
            {
                "job_description": request.job_description,
                "target_role": "ai",
                "max_pages": 3,
            },
        )
        self.assertEqual(self.assembly_request.pages.user_max_pages, 3)

    def test_source_files_never_changed(self):
        svc.generate_resume_from_jd(self.request())
        self.assertEqual(self.profile.read_bytes(), self.original_profile)
        self.assertEqual(self.template.read_bytes(), self.original_template)

    def test_graph_rejection_stops_before_semantic_review(self):
        self.state["quality_passed"] = False
        self.state["evaluation_feedback"] = "Grounding failed"
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual(result.status, "rejected")
        self.assertEqual([x[0] for x in self.calls], ["graph"])
        self.assertNotIn("approved_snapshot", result.artifacts)

    def test_rejected_semantic_review_stops_before_assembly(self):
        self.mock(svc, "_repair_candidate", lambda state, issues, profile: dict(
            state, quality_passed=False, evaluation_feedback="Still unsupported"
        ))
        self.verdict_passes = False
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            [x[0] for x in self.calls],
            ["graph", "grounding", "semantic"],
        )
        self.assertNotIn("assembled_preview_pdf", result.artifacts)

    def test_duplicate_fact_ids_rejected(self):
        self.state["selected_fact_ids"] = ["f", "f"]
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual(result.status, "failed")
        self.assertIn("selected_fact_ids", " ".join(result.errors))
        self.assertNotIn("assembly", [x[0] for x in self.calls])

    def test_missing_document_rejected(self):
        self.state.pop("resume_document")
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual(result.status, "failed")
        self.assertNotIn("assembly", [x[0] for x in self.calls])

    def test_profile_changed_during_graph_aborts_run(self):
        def mutate(inputs):
            self.profile.write_text("altered", encoding="utf-8")
            return self.state

        self.mock(svc, "_graph_invoke", mutate)
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual(result.status, "failed")
        self.assertIn("Profile changed", " ".join(result.errors))

    def test_bad_semantic_document_hash_blocks_assembly(self):
        original = self.semantic

        def tamper(candidate, output):
            result = original(candidate, output)
            saved = json.loads(
                Path(output).read_text(encoding="utf-8")
            )
            saved["semantic_recheck"]["document_sha256"] = "tampered"
            Path(output).write_text(
                json.dumps(saved), encoding="utf-8"
            )
            return result

        self.mock(svc, "semantic_recheck_and_save", tamper)
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual(result.status, "failed")
        self.assertNotIn("assembly", [x[0] for x in self.calls])

    def test_fresh_run_uses_new_not_old_snapshot(self):
        result = svc.generate_resume_from_jd(self.request())
        candidate = Path(result.artifacts["candidate_snapshot"])
        approved = Path(result.artifacts["approved_snapshot"])
        self.assertTrue(candidate.is_file() and approved.is_file())
        self.assertNotEqual(candidate, approved)
        self.assertEqual(
            self.assembly_request.approved_snapshot_path, approved
        )

    def test_nonselected_insert_id_is_not_forced(self):
        choice = InsertionChoice(
            work_ids=["work_1", "work_not_selected"],
            experience_anchor="Experience",
            project_anchor="AI Projects",
            experience_style_from="Sample Role",
            project_style_from="Sample Project",
        )
        result = svc.generate_resume_from_jd(
            self.request(insertion=choice)
        )
        self.assertEqual(
            self.assembly_request.insertion.work_ids, ["work_1"]
        )
        self.assertTrue(
            any("not selected" in w for w in result.warnings)
        )

    def test_run_folders_are_isolated(self):
        a = svc.generate_resume_from_jd(self.request())
        b = svc.generate_resume_from_jd(self.request())
        self.assertNotEqual(a.run_directory, b.run_directory)
        self.assertNotEqual(
            a.artifacts["approved_snapshot"],
            b.artifacts["approved_snapshot"],
        )

    def test_assembly_failure_propagates(self):
        def broken(_request):
            return ResumePipelineResult(
                run_id="broken",
                run_directory="broken",
                status="failed",
                errors=["Converter unavailable"],
            )

        self.mock(svc, "assemble_resume", broken)
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual(result.status, "failed")
        self.assertTrue(
            any("Converter unavailable" in e for e in result.errors)
        )

    def test_false_assembly_success_missing_pdf_is_rejected(self):
        def incomplete(request):
            return ResumePipelineResult(
                run_id="missing",
                run_directory=str(request.output_root),
                status="needs_review",
                automated_checks_passed=True,
            )

        self.mock(svc, "assemble_resume", incomplete)
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual(result.status, "failed")
        self.assertIn("without artifact", " ".join(result.errors))

    def test_semantic_failure_repairs_then_independently_passes(self):
        self.verdict_passes = False
        def repair(state, issues, profile):
            self.calls.append(("repair", list(issues)))
            self.assertEqual(issues, ["Unproven metric"])
            self.verdict_passes = True
            return dict(state, revision_count=2)
        self.mock(svc, "_repair_candidate", repair)
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual([x[0] for x in self.calls], [
            "graph", "grounding", "semantic", "repair",
            "grounding", "semantic", "assembly",
        ])
        self.assertEqual(len(result.semantic_history), 2)
        self.assertTrue(result.semantic_passed)
        root = Path(result.run_directory)
        self.assertFalse(json.loads((root / "semantic_result.json").read_text())["quality_passed"])
        self.assertTrue((root / "candidate_attempt_1.json").exists())

    def test_two_repairs_exhausted_preserve_all_attempts(self):
        self.verdict_passes = False
        repairs = []
        def repair(state, issues, profile):
            repairs.append(list(issues))
            return dict(state, revision_count=state["revision_count"] + 1)
        self.mock(svc, "_repair_candidate", repair)
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual(result.status, "rejected")
        self.assertEqual(len(repairs), 2)
        self.assertEqual(len(result.semantic_history), 3)
        self.assertNotIn("assembly", [x[0] for x in self.calls])
        self.assertEqual(len(set(x["candidate"] for x in result.semantic_history)), 3)
        for item in result.semantic_history:
            self.assertTrue(Path(item["candidate"]).is_file())
            self.assertFalse(json.loads(Path(item["verdict"]).read_text())["quality_passed"])

    def test_grounding_failure_blocks_semantic_and_assembly(self):
        def fail(_):
            raise ValueError("Deterministic grounding failed")
        self.mock(svc, "load_candidate_for_recheck", fail)
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual(result.status, "failed")
        self.assertEqual([x[0] for x in self.calls], ["graph"])

    def test_repair_exception_stops_without_assembly(self):
        self.verdict_passes = False
        def fail(*_):
            raise ValueError("Malformed revised JSON")
        self.mock(svc, "_repair_candidate", fail)
        result = svc.generate_resume_from_jd(self.request())
        self.assertEqual(result.status, "failed")
        self.assertNotIn("assembly", [x[0] for x in self.calls])



class SemanticRepairNodeTests(unittest.TestCase):
    def setUp(self):
        from backend.app.models.profile import MasterProfile
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.profile_path = Path(self.folder.name) / "profile.json"
        self.profile = MasterProfile.model_validate({
            "name": "Candidate", "skills": ["Python"],
            "education": [{"institution": "Example University", "degree": "BS Computer Science"}],
            "work_items": [{
                "id": "demo", "name": "Demo", "category": "project",
                "description": "A Python tool", "facts": [{
                    "id": "fact", "description": "Built a Python command line tool."
                }],
            }],
        })
        self.profile_path.write_text(self.profile.model_dump_json())
        self.document = {
            "headline": "Python Developer",
            "summary": "Python developer with experience building command line tools.",
            "skill_groups": [{"title": "Languages", "skills": ["Python"]}],
            "entries": [{"work_id": "demo", "section": "project", "bullets": [{
                "fact_id": "fact", "text": "Built a Python command line tool."
            }]}],
        }
        self.state = dict(
            job_description="Hiring a Python developer for command line tooling.",
            target_role="ai", max_pages=2, selected_fact_ids=["fact"],
            resume_document=self.document, revision_count=2, quality_passed=True,
        )
        self.writer_patch = patch(
            "backend.app.agents.resume_writer.resume_writer_node",
            return_value={"resume_document": self.document},
        )
        self.writer = self.writer_patch.start()
        self.addCleanup(self.writer_patch.stop)
        self.eval_patch = patch(
            "backend.app.agents.resume_evaluator.resume_evaluator_node",
            return_value={"quality_passed": True, "evaluation_feedback": "Grounded"},
        )
        self.evaluator = self.eval_patch.start()
        self.addCleanup(self.eval_patch.stop)
        hook = patch("backend.app.services.profile_store.load_profile", return_value=self.profile)
        hook.start()
        self.addCleanup(hook.stop)

    def test_exact_issues_and_rerendered_document_reach_nodes(self):
        issues = ["Summary overstates Flutter", "Unsupported vector indexing"]
        result = svc._repair_candidate(self.state, issues, self.profile_path)
        sent = self.writer.call_args.args[0]
        for issue in issues:
            self.assertIn(issue, sent["evaluation_feedback"])
        self.assertTrue(sent["resume_draft"])
        self.assertFalse(sent["quality_passed"])
        evaluated = self.evaluator.call_args.args[0]
        self.assertEqual(evaluated["resume_document"], result["resume_document"])
        self.assertEqual(evaluated["resume_draft"], result["resume_draft"])
        self.assertEqual(result["selected_fact_ids"], ["fact"])
        self.assertEqual(result["revision_count"], 3)
        self.assertTrue(self.state["quality_passed"])

    def test_missing_or_malformed_revised_document_blocks_evaluator(self):
        for update in ({}, {"resume_document": {}}, {"resume_document": "bad JSON"}):
            with self.subTest(update=update):
                self.writer.return_value = update
                with self.assertRaises(ValueError):
                    svc._repair_candidate(self.state, ["Fix claim"], self.profile_path)
        self.evaluator.assert_not_called()

    def test_wrong_fact_ownership_blocks_evaluator(self):
        from copy import deepcopy
        bad = deepcopy(self.document)
        bad["entries"][0]["bullets"][0]["fact_id"] = "unknown"
        self.writer.return_value = {"resume_document": bad}
        with self.assertRaises(ValueError):
            svc._repair_candidate(self.state, ["Fix claim"], self.profile_path)
        self.evaluator.assert_not_called()

    def test_invalid_evaluator_output_is_error(self):
        self.evaluator.return_value = {"quality_passed": "true"}
        with self.assertRaisesRegex(ValueError, "invalid output"):
            svc._repair_candidate(self.state, ["Fix claim"], self.profile_path)

    def test_bridge_failure_propagates(self):
        self.writer.side_effect = ConnectionError("Bridge unavailable")
        with self.assertRaises(ConnectionError):
            svc._repair_candidate(self.state, ["Fix claim"], self.profile_path)
        self.evaluator.assert_not_called()

    def test_profile_change_is_error(self):
        def change(_):
            self.profile_path.write_text("changed")
            return {"quality_passed": True, "evaluation_feedback": "Grounded"}
        self.evaluator.side_effect = change
        with self.assertRaisesRegex(RuntimeError, "Profile changed"):
            svc._repair_candidate(self.state, ["Fix claim"], self.profile_path)



class SnapshotAssemblyIntegrationTests(unittest.TestCase):
    """Prove both modes share a single assembly and header-cleanup stage."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.profile = self.root / "profile.json"
        self.template = self.root / "template.docx"
        self.approved = self.root / "approved.json"
        self.profile.write_text("{}", encoding="utf-8")
        self.template.write_bytes(b"template fixture")
        self.approved.write_text("{}", encoding="utf-8")
        self.calls = []

        self.mock(svc, "PROFILE_PATH", self.profile)
        self.mock(svc, "_approved_snapshot_copy", self.approval)
        self.mock(
            svc,
            "resolve_page_policy",
            lambda *_: type("Policy", (), {"conflicts": []})(),
        )
        self.mock(svc, "write_dynamic_resume_preview", self.preview)
        self.mock(svc, "audit_resume_content", self.content)
        self.mock(svc, "export_docx_to_pdf", self.pdf)
        self.mock(svc, "audit_resume_layout", self.layout)

    def mock(self, obj, name, value):
        hook = patch.object(obj, name, value)
        hook.start()
        self.addCleanup(hook.stop)

    def approval(self, src, dest, profile):
        self.calls.append("approval")
        dest.write_text("{}", encoding="utf-8")
        return {
            "resume_document": {
                "entries": [{"work_id": "work_1"}]
            }
        }

    def preview(self, template, approved, output):
        self.calls.append("preview")
        output.write_bytes(b"preview fixture")
        return {
            "skipped": [],
            "updated_work_ids": ["work_1"],
        }

    def content(self, **kwargs):
        self.calls.append("content")
        from pydantic import BaseModel

        class Fake(BaseModel):
            approved_content_complete: bool = True
            errors: list[str] = []
            warnings: list[str] = []
            entries: list = []
            retained_template_entries: list = []
            omitted_selected_facts: list = []

        return Fake()

    def pdf(self, source, target, **kwargs):
        self.calls.append("pdf")
        target.write_bytes(b"mock pdf")
        return target

    def layout(self, **kwargs):
        self.calls.append("layout")
        from pydantic import BaseModel

        class Fake(BaseModel):
            automated_checks_passed: bool = True
            errors: list[str] = []
            warnings: list[str] = []
            page_images: list[str] = []

        return Fake()

    def request(self, **changes):
        from backend.app.models.resume_pipeline_result import (
            ResumeAssemblyRequest,
        )

        values = dict(
            template_path=self.template,
            approved_snapshot_path=self.approved,
            profile_path=self.profile,
            output_root=self.root / "runs",
        )
        values.update(changes)
        return ResumeAssemblyRequest(**values)

    def test_snapshot_mode_still_builds_pdf(self):
        result = svc.assemble_resume(self.request())
        self.assertEqual(result.status, "needs_review")
        self.assertTrue(result.automated_checks_passed)
        self.assertEqual(
            self.calls,
            ["approval", "preview", "content", "pdf", "pdf", "layout"],
        )
        self.assertTrue(
            Path(result.artifacts["assembled_preview_pdf"]).is_file()
        )

    def test_header_cleanup_runs_before_content_audit(self):
        import sys
        import types
        from backend.app.models.resume_pipeline_result import (
            ContinuationHeaderChoice,
        )

        module = types.ModuleType(
            "backend.app.services.continuation_header_policy"
        )

        def clean(**kwargs):
            self.calls.append(
                "header-dry" if kwargs["dry_run"] else "header-apply"
            )
            if not kwargs["dry_run"]:
                Path(kwargs["output_path"]).write_bytes(
                    b"no duplicate header"
                )
            return {"planned_removed_paragraphs": 2}

        module.remove_redundant_continuation_header = clean

        header = ContinuationHeaderChoice(
            identity="Candidate",
            repeated_heading="Candidate | Projects",
            repeated_links="portfolio | github",
            next_section="Projects",
        )

        with patch.dict(
            sys.modules,
            {"backend.app.services.continuation_header_policy": module},
        ):
            result = svc.assemble_resume(
                self.request(continuation_header=header)
            )

        self.assertEqual(
            self.calls,
            [
                "approval",
                "preview",
                "header-dry",
                "header-apply",
                "content",
                "pdf",
                "pdf",
                "layout",
            ],
        )
        self.assertTrue(
            result.artifacts["assembled_preview_docx"].endswith(
                "header_cleaned.docx"
            )
        )

    def test_failed_header_validation_does_not_audit_or_render(self):
        import sys
        import types
        from backend.app.models.resume_pipeline_result import (
            ContinuationHeaderChoice,
        )

        module = types.ModuleType(
            "backend.app.services.continuation_header_policy"
        )

        def fail(**kwargs):
            raise ValueError(
                "Header identity could not be verified"
            )

        module.remove_redundant_continuation_header = fail

        header = ContinuationHeaderChoice(
            identity="Candidate",
            repeated_heading="Candidate | Projects",
            repeated_links="portfolio | github",
            next_section="Projects",
        )

        with patch.dict(
            sys.modules,
            {"backend.app.services.continuation_header_policy": module},
        ):
            result = svc.assemble_resume(
                self.request(continuation_header=header)
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(self.calls, ["approval", "preview"])

    def test_approved_slot_is_not_inserted_twice(self):
        from backend.app.models.resume_pipeline_result import (
            InsertionChoice,
        )

        choice = InsertionChoice(
            work_ids=["work_1"],
            experience_anchor="Experience",
            project_anchor="Projects",
            experience_style_from="Role",
            project_style_from="Project",
        )

        def forbid(**_):
            self.fail(
                "Existing approved slot must not be inserted twice"
            )

        self.mock(svc, "insert_missing_approved_entries", forbid)

        result = svc.assemble_resume(
            self.request(insertion=choice)
        )
        self.assertEqual(result.status, "needs_review")
        self.assertNotIn("insertion", self.calls)


if __name__ == "__main__":
    unittest.main()
