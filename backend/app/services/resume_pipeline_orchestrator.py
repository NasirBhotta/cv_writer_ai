
"""One orchestration layer for snapshot assembly and fresh-JD generation.

Existing LangGraph, semantic reviewer, template editor, inserter and layout QA
are reused unchanged. Current single-user PROFILE_PATH only.
"""

import hashlib
import json
import shutil

from pathlib import Path
from uuid import uuid4

from backend.app.models.resume_pipeline_result import (
    FreshResumeRequest,
    ResumeAssemblyRequest,
    ResumePipelineResult,
)
from backend.app.models.page_layout_policy import PageRequirements
from backend.app.services.profile_store import PROFILE_PATH
from backend.app.services.snapshot_semantic_recheck import (
    document_hash,
    load_candidate_for_recheck,
    semantic_recheck_and_save,
)
from backend.app.services.dynamic_resume_preview import (
    write_dynamic_resume_preview,
)
from backend.app.services.safe_entry_inserter import (
    insert_missing_approved_entries,
)
from backend.app.services.safe_entry_removal import (
    plan_entry_removal,
    apply_entry_removal,
)
from backend.app.services.resume_content_audit import (
    audit_resume_content,
)
from backend.app.services.resume_layout_qa import (
    resolve_page_policy,
    export_docx_to_pdf,
    audit_resume_layout,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value) -> None:
    """Write without overwriting pre-existing files."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, default=str)


def _new_run(output_root: Path) -> tuple[str, Path]:
    run_id = uuid4().hex[:16]
    directory = output_root.resolve() / f"run-{run_id}"
    directory.mkdir(parents=True, exist_ok=False)
    return run_id, directory


def _save_run_report(directory: Path, result: ResumePipelineResult) -> None:
    result.artifacts["report"] = str(directory / "pipeline_report.json")
    _write_json(directory / "pipeline_report.json", result)


def _approved_snapshot_copy(
    source: Path, destination: Path, profile: Path,
) -> dict:
    raw = json.loads(source.read_text(encoding="utf-8-sig"))
    semantic = raw.get("semantic_recheck") or {}
    document = raw.get("resume_document")

    if not (
        raw.get("quality_passed") is True
        and raw.get("run_status") == "rechecked_approved"
        and semantic.get("passed") is True
        and isinstance(document, dict)
        and semantic.get("document_sha256") == document_hash(document)
        and raw.get("profile_sha256") == _digest(profile)
    ):
        raise ValueError("Invalid semantic approval or profile/document hash.")

    # Independent deterministic grounding validation, no LLM.
    load_candidate_for_recheck(source)

    before = _digest(source)
    with source.open("rb") as inp, destination.open("xb") as out:
        shutil.copyfileobj(inp, out)
    if _digest(source) != before or _digest(destination) != before:
        raise RuntimeError("Approved snapshot changed during copy.")
    return raw


def _graph_invoke(inputs: dict) -> dict:
    """Existing graph is imported lazily so offline tests never start an LLM."""
    from backend.app.agents.graph import graph
    return dict(graph.invoke(inputs))


def _repair_candidate(state: dict, issues: list[str], profile: Path) -> dict:
    """Continue the existing writer/evaluator without restarting fact selection."""
    from copy import deepcopy
    from backend.app.agents.resume_writer import resume_writer_node
    from backend.app.agents.resume_evaluator import resume_evaluator_node
    from backend.app.models.resume_document import ResumeDocument
    from backend.app.services.profile_store import load_profile
    from backend.app.services.career_context import build_career_context
    from backend.app.services.resume_grounding import validate_resume_document
    from backend.app.services.resume_renderer import render_resume_document
    from backend.app.services.career_validator import validate_resume_draft

    revised = deepcopy(state)
    selected = list(state["selected_fact_ids"])
    context = build_career_context(load_profile(), selected)
    # Regenerate the previous draft from its authoritative document so revision
    # instructions are present even when the graph did not retain draft text.
    revised["resume_draft"] = render_resume_document(
        ResumeDocument.model_validate(state["resume_document"]), context,
    )
    revised["evaluation_feedback"] = (
        "Independent semantic reviewer rejected this document. "
        "Correct every issue without adding unsupported claims:\n"
        + "\n".join(issues)
    )
    revised["quality_passed"] = False
    fingerprint = _digest(profile)
    update = resume_writer_node(deepcopy(revised))
    if not isinstance(update, dict) or not isinstance(update.get("resume_document"), dict):
        raise ValueError("Repair writer returned no structured resume_document.")
    document = ResumeDocument.model_validate(update["resume_document"])
    errors = validate_resume_document(document, context)
    draft = render_resume_document(document, context)
    errors.extend(validate_resume_draft(draft, context))
    if errors:
        raise ValueError("Repair grounding failed: " + "; ".join(errors))
    revised.update(
        resume_document=document.model_dump(mode="json"),
        resume_draft=draft,
        revision_count=state.get("revision_count", 0) + 1,
    )
    verdict = resume_evaluator_node(deepcopy(revised))
    if (
        not isinstance(verdict, dict)
        or type(verdict.get("quality_passed")) is not bool
        or not isinstance(verdict.get("evaluation_feedback"), str)
        or not verdict["evaluation_feedback"].strip()
    ):
        raise ValueError("Repair evaluator returned invalid output.")
    revised.update(
        quality_passed=verdict["quality_passed"],
        evaluation_feedback=verdict["evaluation_feedback"],
    )
    if _digest(profile) != fingerprint:
        raise RuntimeError("Profile changed during semantic repair.")
    return revised


def _save_graph_candidate(state: dict, profile: Path, path: Path) -> None:
    document = state.get("resume_document")
    ids = state.get("selected_fact_ids")

    if state.get("quality_passed") is not True:
        raise ValueError("Graph did not approve the candidate.")
    if not isinstance(document, dict):
        raise ValueError("Graph returned no structured resume_document.")
    if (
        not isinstance(ids, list)
        or not ids
        or any(not isinstance(x, str) or not x for x in ids)
        or len(ids) != len(set(ids))
    ):
        raise ValueError("Graph returned invalid selected_fact_ids.")

    _write_json(path, {
        "resume_document": document,
        "selected_fact_ids": ids,
        "quality_passed": True,
        "evaluation_feedback": state.get("evaluation_feedback", ""),
        "profile_sha256": _digest(profile),
        "run_status": "completed",
        "revision_count": state.get("revision_count", 0),
        "error": None,
    })


def assemble_resume(request: ResumeAssemblyRequest) -> ResumePipelineResult:
    """Existing approved snapshot -> template-aware DOCX/PDF review package."""
    run_id, directory = _new_run(request.output_root)
    result = ResumePipelineResult(
        run_id=run_id, run_directory=str(directory),
    )
    stage = "preflight"

    try:
        template = request.template_path.resolve()
        source_snapshot = request.approved_snapshot_path.resolve()
        profile = request.profile_path.resolve()

        if profile != Path(PROFILE_PATH).resolve():
            raise ValueError(
                "Custom profiles are not yet supported by existing graph/editors."
            )

        for name, path in (
            ("template", template),
            ("snapshot", source_snapshot),
            ("profile", profile),
        ):
            if not path.is_file():
                raise FileNotFoundError(f"Missing {name}: {path}")
        if template.suffix.lower() != ".docx":
            raise ValueError("Template must be .docx.")

        policy = resolve_page_policy(request.pages)
        if policy.conflicts:
            result.review_reasons.extend(policy.conflicts)
            result.status = "needs_review"
            return result

        original_hashes = {
            "template": _digest(template),
            "approved_snapshot": _digest(source_snapshot),
            "profile": _digest(profile),
        }
        result.sha256.update(original_hashes)
        result.artifacts["original_template"] = str(template)

        stage = "approval"
        approved_copy = directory / "approved_snapshot.json"
        approved = _approved_snapshot_copy(
            source_snapshot, approved_copy, profile,
        )
        result.artifacts["snapshot"] = str(approved_copy)
        approved_ids = {
            entry["work_id"]
            for entry in approved["resume_document"]["entries"]
        }

        stage = "preview"
        current = directory / "preview.docx"
        preview = write_dynamic_resume_preview(
            template, approved_copy, current,
        )
        if not current.is_file():
            raise RuntimeError("Preview editor did not create a DOCX.")
        result.artifacts["preview_docx"] = str(current)
        _write_json(directory / "preview_details.json", preview)
        result.artifacts["preview_details"] = str(
            directory / "preview_details.json"
        )
        skipped = preview.get("skipped", [])
        if skipped:
            result.warnings.append(
                "Template preview skipped entries; content audit will verify."
            )

        # Explicit insertion only; never invent or silently insert entries.
        if request.insertion is not None:
            stage = "insertion"
            choice = request.insertion
            if not set(choice.work_ids).issubset(approved_ids):
                raise ValueError("Insertion requested for non-approved work IDs.")

            already_updated = set(preview.get("updated_work_ids", []))
            skip_reasons = {}
            for item in skipped:
                if not isinstance(item, str) or ": " not in item:
                    raise ValueError("Unsupported preview skip report.")
                work_id, reason = item.split(": ", 1)
                skip_reasons[work_id] = reason

            to_insert = []
            for work_id in choice.work_ids:
                if work_id in already_updated:
                    result.warnings.append(
                        f"{work_id}: already updated; insertion not needed."
                    )
                elif skip_reasons.get(work_id) == "no unique approved template slot":
                    to_insert.append(work_id)
                else:
                    result.review_reasons.append(
                        f"{work_id}: not safely classified as a missing slot."
                    )
                    result.status = "needs_review"
                    return result

            if to_insert:
                output = directory / "inserted.docx"
                kwargs = dict(
                    source_path=current,
                    snapshot_path=approved_copy,
                    output_path=output,
                    work_ids=to_insert,
                    experience_anchor=choice.experience_anchor,
                    project_anchor=choice.project_anchor,
                    experience_style_from=choice.experience_style_from,
                    project_style_from=choice.project_style_from,
                )
                plan = insert_missing_approved_entries(
                    **kwargs, dry_run=True,
                )
                _write_json(directory / "insertion_plan.json", plan)
                result.artifacts["insertion_plan"] = str(
                    directory / "insertion_plan.json"
                )
                result.warnings.extend(plan.get("warnings", []))

                if plan.get("requires_review") or plan.get("can_apply") is False:
                    result.review_reasons.append(
                        "Insertion planner requested manual review."
                    )
                    result.status = "needs_review"
                    return result

                insert_missing_approved_entries(
                    **kwargs, dry_run=False,
                )
                if not output.is_file():
                    raise RuntimeError("Insertion stage did not create DOCX.")
                current = output
                result.artifacts["inserted_docx"] = str(output)

        if request.removal is not None:
            stage = "removal"
            choice = request.removal
            kwargs = dict(
                source_path=current,
                snapshot_path=approved_copy,
                section_start=choice.section_start,
                section_end=choice.section_end,
                remove_titles=choice.titles,
            )
            removal_plan = plan_entry_removal(**kwargs)
            _write_json(directory / "removal_plan.json", removal_plan)
            result.artifacts["removal_plan"] = str(
                directory / "removal_plan.json"
            )
            if not removal_plan.can_apply:
                result.review_reasons.append("Removal plan is unsafe.")
                result.status = "needs_review"
                return result

            output = directory / "removed.docx"
            apply_entry_removal(**kwargs, output_path=output)
            if not output.is_file():
                raise RuntimeError("Removal stage did not create DOCX.")
            current = output
            result.artifacts["removed_docx"] = str(output)

        # Cleanup is optional, and removes ONLY exact user-approved identity block.
        if request.continuation_header is not None:
            stage = "continuation_header_cleanup"
            from backend.app.services.continuation_header_policy import (
                remove_redundant_continuation_header,
            )
            choice = request.continuation_header
            output = directory / "header_cleaned.docx"
            kwargs = dict(
                source_path=current,
                output_path=output,
                identity=choice.identity,
                repeated_heading=choice.repeated_heading,
                repeated_links=choice.repeated_links,
                next_section=choice.next_section,
            )
            plan = remove_redundant_continuation_header(
                **kwargs, dry_run=True,
            )
            _write_json(directory / "header_plan.json", plan)
            result.artifacts["header_plan"] = str(
                directory / "header_plan.json"
            )
            remove_redundant_continuation_header(
                **kwargs, dry_run=False,
            )
            if not output.is_file():
                raise RuntimeError("Header cleanup did not create DOCX.")
            current = output
            result.artifacts["header_cleaned_docx"] = str(output)

        stage = "content_audit"
        content = audit_resume_content(
            source_path=current,
            snapshot_path=approved_copy,
            profile_path=profile,
            job_description=request.job_description,
        )
        content_report = directory / "content_audit.json"
        _write_json(content_report, content)
        result.artifacts["content_audit"] = str(content_report)
        result.artifacts["assembled_preview_docx"] = str(current)
        result.sha256["assembled_preview_docx"] = _digest(current)

        result.content_automated_passed = (
            content.approved_content_complete and not content.errors
        )
        result.unresolved_work_ids = [
            entry.work_id for entry in content.entries
            if entry.status != "pass"
        ]
        result.retained_template_entries = [
            entry.heading for entry in content.retained_template_entries
        ]
        result.omitted_selected_fact_ids = [
            fact.fact_id for fact in content.omitted_selected_facts
        ]
        result.warnings.extend(content.warnings)
        result.review_reasons.extend(content.errors)
        if result.unresolved_work_ids:
            result.review_reasons.append(
                "Missing or role-review-required approved work entries."
            )
        if result.retained_template_entries:
            result.review_reasons.append("Review retained template-only entries.")
        if result.omitted_selected_fact_ids:
            result.review_reasons.append("Review omitted selected facts.")

        stage = "template_pdf"
        template_pdf = export_docx_to_pdf(
            template,
            directory / "template_reference.pdf",
            engine=request.converter,
        )
        result.artifacts["template_pdf"] = str(template_pdf)

        stage = "pdf"
        pdf = export_docx_to_pdf(
            current,
            directory / "assembled_preview.pdf",
            engine=request.converter,
        )
        result.artifacts["assembled_preview_pdf"] = str(pdf)
        result.sha256["assembled_preview_pdf"] = _digest(pdf)

        stage = "layout_audit"
        layout = audit_resume_layout(
            source_docx=current,
            pdf_path=pdf,
            requirements=request.pages,
            template_pdf_path=template_pdf,
            render_dir=(directory / "page_images") if request.render_images else None,
            pdf_generated_from_source_this_run=True,
        )
        layout_report = directory / "layout_audit.json"
        _write_json(layout_report, layout)
        result.artifacts["layout_audit"] = str(layout_report)
        result.layout_automated_passed = layout.automated_checks_passed
        result.warnings.extend(layout.warnings)
        result.review_reasons.extend(layout.errors)
        if layout.page_images:
            result.artifacts["page_images_dir"] = str(directory / "page_images")

        stage = "integrity"
        if (
            _digest(template) != original_hashes["template"]
            or _digest(source_snapshot) != original_hashes["approved_snapshot"]
            or _digest(profile) != original_hashes["profile"]
            or _digest(current) != result.sha256["assembled_preview_docx"]
        ):
            raise RuntimeError("Input or generated DOCX changed during build.")

        result.automated_checks_passed = (
            result.content_automated_passed
            and result.layout_automated_passed
        )
        if not result.automated_checks_passed:
            result.review_reasons.append("Automated checks did not all pass.")
        result.review_reasons.append(
            "Visual review and template headline/skills reconciliation pending."
        )
        result.status = "needs_review"
        stage = "complete_pending_review"
        return result

    except Exception as exc:
        result.errors.append(f"{type(exc).__name__}: {exc}")
        result.status = "failed"
        return result

    finally:
        result.stopped_at = stage
        try:
            _save_run_report(directory, result)
        except Exception as exc:
            result.errors.append(f"Could not write report: {exc}")
            result.status = "failed"


def generate_resume_from_jd(
    request: FreshResumeRequest,
) -> ResumePipelineResult:
    """Fresh JD -> EXISTING graph -> semantic recheck -> EXISTING assemble_resume."""
    run_id, directory = _new_run(request.output_root)
    result = ResumePipelineResult(
        run_id=run_id, run_directory=str(directory),
    )
    stage = "preflight"

    try:
        profile = Path(PROFILE_PATH).resolve()
        template = request.template_path.resolve()
        if not profile.is_file():
            raise FileNotFoundError("Master career profile is missing.")
        if not template.is_file() or template.suffix.lower() != ".docx":
            raise ValueError("An existing DOCX template is required.")

        original_profile = _digest(profile)
        original_template = _digest(template)
        result.sha256.update(
            profile=original_profile,
            template=original_template,
        )
        _write_json(
            directory / "run_input.json",
            {
                "job_description": request.job_description,
                "target_role": request.target_role,
                "max_pages": request.max_pages,
                "template_path": str(template),
                "profile_sha256": original_profile,
            },
        )
        result.artifacts["run_input"] = str(directory / "run_input.json")

        stage = "langgraph"
        state = _graph_invoke({
            "job_description": request.job_description,
            "target_role": request.target_role,
            "max_pages": request.max_pages,
        })
        result.graph_quality_passed = state.get("quality_passed") is True
        if not result.graph_quality_passed:
            result.status = "rejected"
            result.review_reasons.append(
                "LangGraph evaluation rejected candidate: "
                + str(state.get("evaluation_feedback") or "No feedback")
            )
            return result
        if _digest(profile) != original_profile:
            raise RuntimeError("Profile changed during LangGraph execution.")

        # One initial review plus at most two writer/evaluator repairs.
        issues = []
        for attempt in range(3):
            if _digest(profile) != original_profile:
                raise RuntimeError("Profile changed during semantic recovery.")
            if attempt:
                stage = "semantic_repair"
                state = _repair_candidate(state, issues, profile)
                _write_json(directory / f"repair_state_{attempt}.json", state)
                if _digest(profile) != original_profile:
                    raise RuntimeError("Profile changed during semantic repair.")
                if state.get("quality_passed") is not True:
                    result.status = "rejected"
                    result.review_reasons.append(
                        "Repair evaluator rejected candidate: "
                        + str(state.get("evaluation_feedback") or "No feedback")
                    )
                    return result

            stage = "candidate_snapshot"
            candidate = directory / (
                "candidate.json" if not attempt else f"candidate_attempt_{attempt}.json"
            )
            _save_graph_candidate(state, profile, candidate)
            result.artifacts[f"candidate_attempt_{attempt}"] = str(candidate)
            result.artifacts["candidate_snapshot"] = str(candidate)

            stage = "deterministic_grounding"
            load_candidate_for_recheck(candidate)
            stage = "semantic_recheck"
            approved = directory / (
                "semantic_result.json" if not attempt else f"semantic_attempt_{attempt}.json"
            )
            verdict = semantic_recheck_and_save(candidate, approved)
            result.artifacts[f"semantic_attempt_{attempt}"] = str(approved)
            if approved.is_file():
                result.artifacts["semantic_result"] = str(approved)
            if _digest(profile) != original_profile:
                raise RuntimeError("Profile changed during semantic review.")
            if type(verdict.get("passed")) is not bool:
                raise ValueError("Invalid independent semantic verdict.")
            issues = verdict.get("issues")
            if not isinstance(issues, list) or any(not isinstance(x, str) for x in issues):
                raise ValueError("Invalid independent semantic issues.")
            result.semantic_passed = verdict["passed"]
            result.semantic_history.append({
                "attempt": attempt, "passed": verdict["passed"],
                "issues": list(issues), "candidate": str(candidate),
                "verdict": str(approved),
            })
            if not result.semantic_passed:
                if not issues or not all(x.strip() for x in issues):
                    raise ValueError("Semantic rejection supplied no actionable issues.")
                if attempt == 2:
                    result.status = "rejected"
                    result.review_reasons.extend(issues)
                    result.review_reasons.append("Two semantic repair attempts exhausted.")
                    return result
                continue
            if issues:
                raise ValueError("Semantic approval contains issues.")
            if not approved.is_file():
                raise RuntimeError("Semantic reviewer returned pass without snapshot.")
            raw_approved = json.loads(approved.read_text(encoding="utf-8"))
            semantic = raw_approved.get("semantic_recheck") or {}
            if not (
                raw_approved.get("quality_passed") is True
                and raw_approved.get("run_status") == "rechecked_approved"
                and semantic.get("passed") is True
                and semantic.get("document_sha256")
                == document_hash(raw_approved["resume_document"])
                and document_hash(raw_approved["resume_document"])
                == document_hash(state["resume_document"])
                and raw_approved.get("selected_fact_ids") == state["selected_fact_ids"]
                and raw_approved.get("profile_sha256") == original_profile
            ):
                raise ValueError("Independent approval snapshot is inconsistent.")
            result.artifacts["approved_snapshot"] = str(approved)
            break

        # An optional user's insertion list is filtered to work IDs
        # actually selected by this new JD, not forced into the resume.
        insertion = request.insertion
        if insertion:
            selected_work = {
                entry["work_id"]
                for entry in raw_approved["resume_document"]["entries"]
            }
            requested = [x for x in insertion.work_ids if x in selected_work]
            for ignored in insertion.work_ids:
                if ignored not in selected_work:
                    result.warnings.append(
                        f"{ignored}: not selected for this JD; not inserted."
                    )
            insertion = insertion.model_copy(update={"work_ids": requested}) if requested else None

        stage = "assemble"
        assembled = assemble_resume(ResumeAssemblyRequest(
            template_path=template,
            approved_snapshot_path=approved,
            profile_path=profile,
            output_root=directory / "assembly",
            job_description=request.job_description,
            pages=PageRequirements(user_max_pages=request.max_pages),
            converter=request.converter,
            insertion=insertion,
            removal=request.removal,
            continuation_header=request.continuation_header,
            render_images=request.render_images,
        ))
        result.artifacts["assembly_report"] = assembled.artifacts.get("report", "")
        for key, value in assembled.artifacts.items():
            if key != "report":
                result.artifacts[key] = value
        result.content_automated_passed = assembled.content_automated_passed
        result.layout_automated_passed = assembled.layout_automated_passed
        result.automated_checks_passed = assembled.automated_checks_passed
        result.unresolved_work_ids = assembled.unresolved_work_ids
        result.retained_template_entries = assembled.retained_template_entries
        result.omitted_selected_fact_ids = assembled.omitted_selected_fact_ids
        result.review_reasons.extend(assembled.review_reasons)
        result.warnings.extend(assembled.warnings)
        result.errors.extend(assembled.errors)

        if assembled.status == "failed":
            result.status = "failed"
            return result

        if assembled.automated_checks_passed:
            for key in ("assembled_preview_docx", "assembled_preview_pdf"):
                value = assembled.artifacts.get(key)
                if not value or not Path(value).is_file():
                    raise RuntimeError(
                        f"Assembly claimed success without artifact: {key}."
                    )

        stage = "integrity"
        if _digest(profile) != original_profile or _digest(template) != original_template:
            raise RuntimeError("Master profile or template changed during run.")

        result.status = "needs_review"  # even if automated checks passed
        stage = "complete_pending_review"
        return result

    except Exception as exc:
        result.status = "failed"
        result.errors.append(f"{type(exc).__name__}: {exc}")
        return result

    finally:
        result.stopped_at = stage
        try:
            _save_run_report(directory, result)
        except Exception as exc:
            result.status = "failed"
            result.errors.append(f"Could not write report: {exc}")
