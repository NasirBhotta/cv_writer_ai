# Backend App File Guide

Python source files in backend/app and their responsibilities. Tests, template assets, generated outputs, and caches are excluded.

## agents

- **agents/audit_resume_content.py** — CLI for auditing approved resume content without editing the DOCX.
- **agents/build_resume.py** — CLI for assembling a DOCX/PDF review package from an approved snapshot.
- **agents/export_saved_docx.py** — CLI for exporting a saved structured resume to a DOCX template.
- **agents/finish_resume_backend.py** — CLI for offline validation, semantic rechecks, and dynamic DOCX previews.
- **agents/graph.py** — Builds the LangGraph workflow for JD analysis, fact selection, writing, and evaluation.
- **agents/inspect_template.py** — CLI for inspecting a DOCX template and mapping its editable sections.
- **agents/jd_analyzer.py** — Uses an LLM to extract structured requirements from a job description.
- **agents/preview_saved_resume.py** — CLI for planning and writing a template preview from a saved resume.
- **agents/repair_saved_resume.py** — CLI for repairing saved resume bullets using profile evidence.
- **agents/resume_evaluator.py** — Evaluates generated resumes with deterministic grounding checks and LLM review.
- **agents/resume_writer.py** — Generates a structured resume from selected career facts using an LLM.
- **agents/review_entry_removal.py** — CLI for planning or applying explicitly selected DOCX entry removals.
- **agents/run_debug.py** — Runs an example resume graph, prints progress, and saves completion or failure snapshots.
- **agents/state.py** — Defines the shared input and output state passed between resume graph nodes.
- **agents/verify_resume_layout.py** — CLI for PDF conversion and rendered resume pagination checks.

## models

- **models/entry_removal_plan.py** — Defines removal targets and the safety findings in an entry removal plan.
- **models/page_layout_policy.py** — Defines page requirements, resolved page policy, and layout QA reports.
- **models/profile.py** — Defines career facts, work history, education, and the master career profile.
- **models/resume_content_audit.py** — Defines content coverage, omitted fact, retained entry, and audit report models.
- **models/resume_document.py** — Defines the structured resume headline, summary, skills, entries, and sourced bullets.
- **models/resume_pipeline_result.py** — Defines snapshot assembly requests, explicit edit choices, and pipeline results.
- **models/saved_resume_preview.py** — Defines saved resume validation and preview manifest models.
- **models/template_edit_plan.py** — Defines paragraph replacements and the edit plan for a DOCX template.
- **models/template_entry_map.py** — Defines template entry slots, matched work items, and document bridge results.
- **models/template_mapping.py** — Defines mapped template sections, sub-blocks, and protected content regions.
- **models/template_report.py** — Defines inspected DOCX blocks, section hints, page layouts, and template reports.

## services

- **services/career_context.py** — Builds and serializes career evidence context from selected profile facts.
- **services/career_validator.py** — Checks career context and rendered resume structure against known profile metadata.
- **services/continuation_header_policy.py** — Removes an explicitly approved redundant continuation header with safety checks.
- **services/docx_exporter.py** — Exports a grounded structured resume into a DOCX template using placeholders.
- **services/dynamic_resume_preview.py** — Updates approved matching template entries and summary in a new DOCX preview.
- **services/llm_client.py** — Wraps the OpenAI client for model generation and API error handling.
- **services/pipeline_cache.py** — Loads and saves pipeline stage results using hashed input cache keys.
- **services/profile_retriever.py** — Uses an LLM to select relevant profile fact IDs for analyzed job requirements.
- **services/profile_store.py** — Loads and saves the master profile and provides personal profile initialization data.
- **services/resume_content_audit.py** — Audits assembled DOCX coverage, evidence, omitted facts, and optional JD relevance.
- **services/resume_entry_bridge.py** — Builds template edit plans by connecting structured resume entries to matched slots.
- **services/resume_grounding.py** — Validates resume fact ownership and sections and builds evidence pairs for review.
- **services/resume_layout_qa.py** — Exports DOCX to PDF and checks rendered page counts against optional page requirements.
- **services/resume_pipeline_orchestrator.py** — Coordinates approved snapshot assembly, content audits, PDF export, and layout review.
- **services/resume_renderer.py** — Renders a structured resume and career context into plain text for evaluation.
- **services/safe_entry_inserter.py** — Validates and inserts explicitly requested approved entries using template prototypes.
- **services/safe_entry_removal.py** — Plans and applies explicitly scoped entry removals while preserving approved bullets.
- **services/saved_resume_preview.py** — Validates saved resume evidence and prepares or writes a conservative template preview.
- **services/snapshot_repair.py** — Repairs snapshot bullets using source facts while retaining evidence references.
- **services/snapshot_semantic_recheck.py** — Validates saved evidence and optionally records an independent LLM semantic verdict.
- **services/template_edit_planner.py** — Builds and validates safe summary and bullet replacement plans for mapped templates.
- **services/template_editor.py** — Applies validated paragraph edits to a new DOCX and verifies the saved structure.
- **services/template_entry_matcher.py** — Matches template entry headings and bullet slots to profile work items.
- **services/template_insertion_locator.py** — Finds candidate insertion sections and style prototypes without editing the DOCX.
- **services/template_inspector.py** — Inspects DOCX text, formatting, layout, and package warnings without editing it.
- **services/template_mapper.py** — Maps inspected template blocks into resume sections and editable regions.
- **services/template_structure.py** — Identifies protected identity content and validates template section structure.
