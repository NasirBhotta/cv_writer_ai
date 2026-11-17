
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from backend.app.models.saved_resume_preview import (
    SavedPreviewManifest,
    SavedResumeRun,
)
from backend.app.models.template_edit_plan import (
    TemplateEditPlan,
)
from backend.app.models.template_mapping import (
    TemplateMapping,
)
from backend.app.services.profile_store import (
    PROFILE_PATH,
    load_profile,
)
from backend.app.services.resume_entry_bridge import (
    build_document_edit_plan,
)
from backend.app.services.template_edit_planner import (
    build_resume_edit_plan,
)
from backend.app.services.template_editor import (
    apply_template_edit_plan,
)
from backend.app.services.template_entry_matcher import (
    map_template_entries,
)
from backend.app.services.template_inspector import (
    inspect_template,
)
from backend.app.services.template_mapper import (
    map_template,
)


@dataclass(frozen=True)
class PreparedPreview:
    mapping: TemplateMapping
    plan: TemplateEditPlan | None
    manifest: SavedPreviewManifest


def _load_saved_run(
    path: str | Path,
) -> SavedResumeRun:
    source = Path(path)

    if not source.is_file():
        raise FileNotFoundError(
            f"Saved run not found: {source}"
        )

    payload = json.loads(
        source.read_text(encoding="utf-8")
    )

    if not isinstance(payload, dict):
        raise ValueError(
            "Saved run must contain a JSON object."
        )

    return SavedResumeRun.model_validate(payload)


def _safe_summary(
    mapping: TemplateMapping,
    summary: str,
) -> bool:
    regions = [
        region
        for region in mapping.regions
        if region.section == "summary"
    ]

    if len(regions) != 1 or regions[0].needs_review:
        return False

    if len(regions[0].content_block_ids) != 1:
        return False

    block_id = regions[0].content_block_ids[0]

    return (
        block_id not in mapping.protected_block_ids
        and bool(summary.strip())
        and summary == summary.strip()
        and not any(
            char in summary
            for char in ("\n", "\r", "\t", "\x00")
        )
    )


def prepare_saved_resume_preview(
    template_path: str | Path,
    snapshot_path: str | Path = (
        ".cache/resume_pipeline/last_resume_run.json"
    ),
    *,
    profile_path: str | Path = PROFILE_PATH,
) -> PreparedPreview:

    # 1. Load already-generated LLM result.
    snapshot = _load_saved_run(snapshot_path)

    # 2. Verify original master profile is unchanged.
    profile_source = Path(profile_path)

    actual_profile_sha = sha256(
        profile_source.read_bytes()
    ).hexdigest()

    if actual_profile_sha != snapshot.profile_sha256:
        raise ValueError(
            "Master profile changed since saved run; "
            "regenerate the resume before using "
            "this snapshot."
        )

    # 3. Load master career profile.
    profile = load_profile()

    # 4. Inspect the user's actual DOCX template.
    report = inspect_template(template_path)
    mapping = map_template(report)

    # 5. Identify actual work/project entries.
    entry_map = map_template_entries(
        report,
        mapping,
        profile.work_items,
    )

    # 6. Bridge structured ResumeDocument to DOCX.
    # Partial matching is allowed for PREVIEW only.
    bridge = build_document_edit_plan(
        report,
        mapping,
        entry_map,
        profile,
        snapshot.resume_document,
        allowed_fact_ids=set(
            snapshot.selected_fact_ids
        ),
        allow_partial=True,
    )

    # 7. Extract safely matched bullet replacements.
    replacements = {}

    if bridge.plan is not None:
        for edit in bridge.plan.edits:
            if edit.mode != "bullet":
                raise ValueError(
                    "Bridge returned an unexpected "
                    "non-bullet edit."
                )

            replacements[edit.block_id] = (
                edit.new_text
            )

    warnings = list(
        dict.fromkeys(
            mapping.warnings + entry_map.warnings
        )
    )

    # 8. Check if template summary is editable.
    summary = snapshot.resume_document.summary

    include_summary = _safe_summary(
        mapping,
        summary,
    )

    if not include_summary:
        warnings.append(
            "Summary has no safe single-paragraph "
            "slot; unchanged."
        )

    if not snapshot.quality_passed:
        warnings.append(
            "Saved evaluator did not pass; "
            "DOCX writing is blocked."
        )

    # 9. Combine summary and bullet edits.
    plan = None

    if include_summary or replacements:
        plan = build_resume_edit_plan(
            report,
            mapping,
            summary=(
                summary
                if include_summary
                else None
            ),
            bullet_replacements=replacements,
        )

    # 10. Identify entries that were actually matched.
    changed = set(replacements)

    updated_work_ids = [
        slot.work_id
        for slot in entry_map.slots
        if (
            slot.work_id
            and slot.bullet_block_ids
            and set(slot.bullet_block_ids) <= changed
        )
    ]

    # 11. Identify original entries left unchanged.
    unchanged = [
        f"{slot.heading_block_id}: "
        f"{slot.heading_text}"
        for slot in entry_map.slots
        if not set(slot.bullet_block_ids) <= changed
    ]

    if unchanged:
        warnings.append(
            "Some original CV entries remain unchanged; "
            "this is NOT a final tailored CV."
        )

    if bridge.skipped:
        warnings.append(
            "Some generated resume entries could not "
            "be mapped safely."
        )

    # 12. Prepare a reviewable preview manifest.
    manifest = SavedPreviewManifest(
        template_path=str(template_path),
        snapshot_path=str(snapshot_path),
        template_sha256=report.sha256,
        profile_sha256=snapshot.profile_sha256,
        quality_passed=snapshot.quality_passed,
        summary_included=include_summary,
        planned_block_ids=[
            edit.block_id
            for edit in plan.edits
        ] if plan else [],
        updated_work_ids=updated_work_ids,
        skipped_entries=bridge.skipped,
        unchanged_template_entries=unchanged,
        warnings=warnings,
    )

    return PreparedPreview(
        mapping=mapping,
        plan=plan,
        manifest=manifest,
    )


def write_saved_resume_preview(
    prepared: PreparedPreview,
    output_path: str | Path,
) -> Path:

    if not prepared.manifest.quality_passed:
        raise ValueError(
            "Saved evaluation did not pass. "
            "Cannot write DOCX preview."
        )

    if prepared.plan is None:
        raise ValueError(
            "No safe DOCX edits were available "
            "for this preview."
        )

    return apply_template_edit_plan(
        prepared.manifest.template_path,
        output_path,
        prepared.mapping,
        prepared.plan,
    )
