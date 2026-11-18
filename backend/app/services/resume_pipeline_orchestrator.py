
"""Fail-closed assembly from an independently approved snapshot.

Not a multi-user graph runner: existing editing services still
consume the repository-global PROFILE_PATH.

No profile monkeypatching, guessed insertions, or auto-deletion.
"""

import hashlib
import json
import shutil

from pathlib import Path
from uuid import uuid4

from backend.app.models.resume_pipeline_result import (
    ResumeAssemblyRequest,
    ResumePipelineResult,
)

from backend.app.services.profile_store import (
    PROFILE_PATH,
)

from backend.app.services.snapshot_semantic_recheck import (
    document_hash,
    load_candidate_for_recheck,
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
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def _report(path: Path, value) -> None:
    if path.exists():
        raise FileExistsError(
            f"Report already exists: {path}"
        )

    path.write_text(
        value.model_dump_json(indent=2),
        encoding="utf-8",
    )


class _RawReport:
    """Serialize a mapping through the exclusive writer."""

    def __init__(self, value: dict):
        self.value = value

    def model_dump_json(
        self,
        indent: int = 2,
    ) -> str:
        return json.dumps(
            self.value,
            indent=indent,
            ensure_ascii=False,
            default=str,
        )


def _copy_approved_snapshot(
    source: Path,
    destination: Path,
    profile: Path,
) -> dict:
    """Validate approval and copy to this run's directory."""

    raw = json.loads(
        source.read_text(
            encoding="utf-8-sig"
        )
    )

    semantic = (
        raw.get("semantic_recheck")
        or {}
    )

    if not (
        raw.get("quality_passed") is True
        and raw.get("run_status")
        == "rechecked_approved"
        and semantic.get("passed") is True
        and isinstance(
            raw.get("resume_document"),
            dict,
        )
        and semantic.get("document_sha256")
        == document_hash(
            raw["resume_document"]
        )
        and raw.get("profile_sha256")
        == _digest(profile)
    ):
        raise ValueError(
            "Snapshot approval or "
            "profile/document fingerprint is invalid."
        )

    # Existing deterministic grounding checks.
    # No LLM call is made here.
    load_candidate_for_recheck(source)

    before = _digest(source)

    with (
        destination.open("xb") as target,
        source.open("rb") as inp,
    ):
        shutil.copyfileobj(
            inp,
            target,
        )

    if (
        _digest(source) != before
        or _digest(destination) != before
    ):
        raise RuntimeError(
            "Approved snapshot changed "
            "while being copied."
        )

    return raw


def assemble_resume(
    request: ResumeAssemblyRequest,
) -> ResumePipelineResult:
    """Create new preview artifacts.

    The original DOCX, snapshot and profile are unchanged.

    Final export approval remains false until human review.
    """

    run_id = uuid4().hex[:16]

    root = request.output_root.resolve()

    directory = (
        root / f"run-{run_id}"
    )

    directory.mkdir(
        parents=True,
        exist_ok=False,
    )

    result = ResumePipelineResult(
        run_id=run_id,
        run_directory=str(directory),
    )

    result.artifacts["report"] = str(
        directory / "pipeline_report.json"
    )

    stage = "preflight"

    try:
        template = (
            request.template_path.resolve()
        )

        source_snapshot = (
            request.approved_snapshot_path.resolve()
        )

        profile = (
            request.profile_path.resolve()
        )

        # Existing graph/editor services load one global
        # profile. Reject arbitrary user paths until
        # dependency injection is implemented.
        if profile != Path(PROFILE_PATH).resolve():
            raise ValueError(
                "Custom profiles are not supported by "
                "the current graph/editors. Profile "
                "dependency injection must be "
                "implemented first."
            )

        for name, path in (
            ("template", template),
            ("snapshot", source_snapshot),
            ("profile", profile),
        ):
            if not path.is_file():
                raise FileNotFoundError(
                    f"Missing {name}: {path}"
                )

        if template.suffix.lower() != ".docx":
            raise ValueError(
                "Template must be .docx"
            )

        policy = resolve_page_policy(
            request.pages
        )

        if policy.conflicts:
            result.review_reasons.extend(
                policy.conflicts
            )

            result.status = "needs_review"
            return result

        template_before = _digest(
            template
        )

        snapshot_before = _digest(
            source_snapshot
        )

        profile_before = _digest(
            profile
        )

        result.sha256.update(
            template=template_before,
            approved_snapshot=snapshot_before,
            profile=profile_before,
        )

        result.artifacts[
            "original_template"
        ] = str(template)

        # STEP 1: Independent approval and hashes.
        stage = "approval"

        approved_copy = (
            directory / "approved_snapshot.json"
        )

        approved = _copy_approved_snapshot(
            source_snapshot,
            approved_copy,
            profile,
        )

        result.artifacts[
            "snapshot"
        ] = str(approved_copy)

        approved_work_ids = {
            item["work_id"]
            for item in approved[
                "resume_document"
            ]["entries"]
        }

        # STEP 2: Existing template-aware preview.
        stage = "preview"

        current = (
            directory / "preview.docx"
        )

        preview_details = (
            write_dynamic_resume_preview(
                template,
                approved_copy,
                current,
            )
        )

        if not current.is_file():
            raise RuntimeError(
                "Preview generator did not "
                "write the DOCX."
            )

        result.artifacts[
            "preview_docx"
        ] = str(current)

        preview_report = (
            directory / "preview_details.json"
        )

        _report(
            preview_report,
            _RawReport(preview_details),
        )

        result.artifacts[
            "preview_details"
        ] = str(preview_report)

        if preview_details.get("skipped"):
            result.warnings.append(
                "Preview skipped entries; final "
                "content audit will check them."
            )

        # STEP 3: Explicitly authorized insertion.
        if request.insertion is not None:
            stage = "insertion"

            choice = request.insertion

            if not set(
                choice.work_ids
            ).issubset(
                approved_work_ids
            ):
                raise ValueError(
                    "Insertion requested for "
                    "non-approved work IDs."
                )

            kwargs = dict(
                source_path=current,
                snapshot_path=approved_copy,
                output_path=(
                    directory / "inserted.docx"
                ),
                work_ids=choice.work_ids,
                experience_anchor=(
                    choice.experience_anchor
                ),
                project_anchor=(
                    choice.project_anchor
                ),
                experience_style_from=(
                    choice.experience_style_from
                ),
                project_style_from=(
                    choice.project_style_from
                ),
            )

            dry_run = (
                insert_missing_approved_entries(
                    **kwargs,
                    dry_run=True,
                )
            )

            insertion_plan = (
                directory / "insertion_plan.json"
            )

            _report(
                insertion_plan,
                _RawReport(dry_run),
            )

            result.artifacts[
                "insertion_plan"
            ] = str(insertion_plan)

            if (
                dry_run.get("requires_review")
                or dry_run.get(
                    "can_apply"
                ) is False
            ):
                result.review_reasons.append(
                    "Insertion plan needs review; "
                    "nothing applied."
                )

                result.status = "needs_review"
                return result

            insert_missing_approved_entries(
                **kwargs,
                dry_run=False,
            )

            current = Path(
                kwargs["output_path"]
            )

            if not current.is_file():
                raise RuntimeError(
                    "Inserter did not create "
                    "the expected DOCX."
                )

            result.artifacts[
                "inserted_docx"
            ] = str(current)

        # STEP 4: Explicitly authorized removal.
        if request.removal is not None:
            stage = "removal"

            choice = request.removal

            kwargs = dict(
                source_path=current,
                snapshot_path=approved_copy,
                section_start=(
                    choice.section_start
                ),
                section_end=(
                    choice.section_end
                ),
                remove_titles=choice.titles,
            )

            plan = plan_entry_removal(
                **kwargs
            )

            removal_plan = (
                directory / "removal_plan.json"
            )

            _report(
                removal_plan,
                plan,
            )

            result.artifacts[
                "removal_plan"
            ] = str(removal_plan)

            if not plan.can_apply:
                result.review_reasons.append(
                    "Removal plan is unsafe; "
                    "no entries removed."
                )

                result.status = "needs_review"
                return result

            output = (
                directory / "removed.docx"
            )

            apply_entry_removal(
                **kwargs,
                output_path=output,
            )

            if not output.is_file():
                raise RuntimeError(
                    "Removal service did not "
                    "create the expected DOCX."
                )

            current = output

            result.artifacts[
                "removed_docx"
            ] = str(current)

        # STEP 5: Re-audit the final assembled DOCX.
        stage = "content_audit"

        content = audit_resume_content(
            source_path=current,
            snapshot_path=approved_copy,
            profile_path=profile,
            job_description=(
                request.job_description
            ),
        )

        content_report = (
            directory / "content_audit.json"
        )

        _report(
            content_report,
            content,
        )

        result.artifacts[
            "content_audit"
        ] = str(content_report)

        result.artifacts[
            "assembled_preview_docx"
        ] = str(current)

        result.sha256[
            "assembled_preview_docx"
        ] = _digest(current)

        result.content_automated_passed = (
            content.approved_content_complete
            and not content.errors
        )

        result.unresolved_work_ids = [
            entry.work_id
            for entry in content.entries
            if entry.status != "pass"
        ]

        result.retained_template_entries = [
            entry.heading
            for entry in (
                content.retained_template_entries
            )
        ]

        result.omitted_selected_fact_ids = [
            fact.fact_id
            for fact in (
                content.omitted_selected_facts
            )
        ]

        if result.unresolved_work_ids:
            result.review_reasons.append(
                "Approved entries are missing, "
                "ambiguous, or need role review."
            )

        if result.retained_template_entries:
            result.review_reasons.append(
                "Template-only entries require "
                "relevance review."
            )

        if result.omitted_selected_fact_ids:
            result.review_reasons.append(
                "Retriever-selected facts were "
                "omitted: review those decisions."
            )

        result.warnings.extend(
            content.warnings
        )

        if content.errors:
            result.review_reasons.extend(
                content.errors
            )

        # STEP 6: Original template PDF.
        stage = "template_pdf"

        template_pdf = export_docx_to_pdf(
            template,
            directory / "template_reference.pdf",
            engine=request.converter,
        )

        result.artifacts[
            "template_pdf"
        ] = str(template_pdf)

        # STEP 7: Export assembled PDF.
        stage = "pdf"

        pdf = export_docx_to_pdf(
            current,
            directory / "assembled_preview.pdf",
            engine=request.converter,
        )

        result.artifacts[
            "assembled_preview_pdf"
        ] = str(pdf)

        result.sha256[
            "assembled_preview_pdf"
        ] = _digest(pdf)

        # STEP 8: Rendered page and layout audit.
        stage = "layout_audit"

        layout = audit_resume_layout(
            source_docx=current,
            pdf_path=pdf,
            requirements=request.pages,
            template_pdf_path=template_pdf,
            render_dir=(
                directory / "page_images"
                if request.render_images
                else None
            ),
            pdf_generated_from_source_this_run=True,
        )

        layout_report = (
            directory / "layout_audit.json"
        )

        _report(
            layout_report,
            layout,
        )

        result.artifacts[
            "layout_audit"
        ] = str(layout_report)

        result.layout_automated_passed = (
            layout.automated_checks_passed
        )

        result.warnings.extend(
            layout.warnings
        )

        if layout.errors:
            result.review_reasons.extend(
                layout.errors
            )

        if layout.page_images:
            result.artifacts[
                "page_images_dir"
            ] = str(
                directory / "page_images"
            )

        # STEP 9: Verify inputs did not change.
        stage = "integrity"

        if (
            _digest(template)
            != template_before
            or _digest(source_snapshot)
            != snapshot_before
            or _digest(profile)
            != profile_before
            or _digest(current)
            != result.sha256[
                "assembled_preview_docx"
            ]
        ):
            raise RuntimeError(
                "Source or assembled DOCX changed "
                "during pipeline."
            )

        result.automated_checks_passed = (
            result.content_automated_passed
            and result.layout_automated_passed
        )

        if not result.automated_checks_passed:
            result.review_reasons.append(
                "Some automated checks did not pass."
            )

        result.review_reasons.append(
            "Human visual QA is required; "
            "headline/skills and template-only "
            "content are not fully synchronized "
            "or visually verified."
        )

        result.status = "needs_review"
        stage = "complete_pending_review"

        return result

    except Exception as exc:
        result.errors.append(
            f"{type(exc).__name__}: {exc}"
        )

        result.status = "failed"
        return result

    finally:
        result.stopped_at = stage

        report_path = (
            directory / "pipeline_report.json"
        )

        try:
            _report(
                report_path,
                result,
            )

        except Exception as exc:
            result.errors.append(
                "Could not write pipeline report: "
                f"{exc}"
            )

            result.status = "failed"
