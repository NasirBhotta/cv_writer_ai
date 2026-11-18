
"""Read-only audit of approved content and optional JD relevance.

Never deletes entries, infers approval for template-only text,
or changes page count.
"""

import json
import re

from collections import Counter
from hashlib import sha256
from pathlib import Path

from docx import Document

from backend.app.models.resume_document import ResumeDocument

from backend.app.models.resume_content_audit import (
    EntryCoverage,
    OmittedFact,
    RetainedTemplateEntry,
    ResumeContentAudit,
)

from backend.app.services.profile_store import PROFILE_PATH

from backend.app.services.snapshot_semantic_recheck import (
    document_hash,
)


_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by",
    "for", "from", "has", "in", "is", "it", "of",
    "on", "or", "our", "the", "to", "we", "with",
    "you", "your", "will", "using", "required",
    "hiring", "junior", "developer", "engineer",
    "experience", "experienced",
}

_MARKERS = ("• ", "- ", "– ")


def _normalize(value: str) -> str:
    """Normalize case, spaces and separator differences."""

    return " ".join(
        re.findall(
            r"\w+",
            value.casefold(),
            flags=re.UNICODE,
        )
    )


def _jd_terms(text: str) -> set[str]:
    return {
        word
        for word in re.findall(
            r"[a-z0-9]+",
            text.casefold(),
        )
        if len(word) >= 3
        and word not in _STOPWORDS
    }


def _heading_text(text: str) -> str:
    # Template headings often separate the
    # right-aligned date with a tab.
    return text.split("\t", 1)[0].strip()


def _candidate_titles(
    work: dict,
    *,
    allow_company_only: bool,
) -> set[str]:
    name = str(
        work.get("name") or ""
    ).strip()

    role = str(
        work.get("role") or ""
    ).strip()

    company = str(
        work.get("organization") or ""
    ).strip()

    titles = {name} if name else set()

    if (
        role
        and company
        and "needs confirmation"
        not in role.casefold()
    ):
        titles.update((
            f"{role} — {company}",
            f"{company} — {role}",
        ))

    if company and allow_company_only:
        titles.add(company)

    return {
        _normalize(title)
        for title in titles
        if title
    }


def _matching_headings(
    paragraphs: list,
    titles: set[str],
) -> list[int]:
    return [
        index
        for index, paragraph in enumerate(
            paragraphs
        )
        if (
            paragraph.text.strip()
            and not paragraph.text.startswith(
                _MARKERS
            )
            and _normalize(
                _heading_text(paragraph.text)
            ) in titles
        )
    ]


def _adjacent_bullets(
    paragraphs: list,
    start: int,
) -> list[str]:
    """
    Read a heading's following bullet block.

    Empty spacer paragraphs are allowed.
    Unrelated content closes the entry.
    """

    result: list[str] = []

    for paragraph in paragraphs[
        start + 1:
    ]:
        text = paragraph.text.strip()

        if not text:
            # Do not cross manual page/section
            # breaks embedded in empty paragraphs.
            if (
                paragraph._p.xpath(".//w:br")
                or paragraph._p.xpath(".//w:sectPr")
            ):
                break

            continue

        if paragraph.text.startswith(
            _MARKERS
        ):
            result.append(
                _normalize(
                    paragraph.text[2:]
                )
            )

        else:
            break

    return result


def audit_resume_content(
    *,
    source_path: str | Path,
    snapshot_path: str | Path,
    profile_path: str | Path = PROFILE_PATH,
    job_description: str | None = None,
) -> ResumeContentAudit:
    """
    Validate evidence and audit the assembled DOCX.

    No LLM calls, no DOCX writing, no deletions.
    """

    source = Path(source_path)
    snapshot_file = Path(snapshot_path)
    profile_file = Path(profile_path)

    source_hash = sha256(
        source.read_bytes()
    ).hexdigest()

    # Step 1: Validate approved snapshot.
    snapshot = json.loads(
        snapshot_file.read_text(
            encoding="utf-8-sig"
        )
    )

    profile_bytes = (
        profile_file.read_bytes()
    )

    if snapshot.get("profile_sha256") != (
        sha256(profile_bytes).hexdigest()
    ):
        raise ValueError(
            "Master profile SHA-256 mismatch."
        )

    approval = snapshot.get(
        "semantic_recheck"
    ) or {}

    if not (
        snapshot.get("quality_passed") is True
        and snapshot.get("run_status")
        == "rechecked_approved"
        and approval.get("passed") is True
        and approval.get("document_sha256")
        == document_hash(
            snapshot["resume_document"]
        )
    ):
        raise ValueError(
            "Snapshot lacks valid semantic "
            "approval/fingerprint."
        )

    selected = snapshot.get(
        "selected_fact_ids"
    )

    if (
        not isinstance(selected, list)
        or not selected
        or len(selected) != len(set(selected))
    ):
        raise ValueError(
            "Invalid or duplicate selected_fact_ids."
        )

    selected_set = set(selected)

    # Step 2: Index authoritative career facts.
    profile = json.loads(
        profile_bytes.decode("utf-8-sig")
    )

    work_items = profile.get(
        "work_items"
    )

    if not isinstance(
        work_items, list
    ):
        raise ValueError(
            "Master profile has no work_items list."
        )

    works = {
        work["id"]: work
        for work in work_items
    }

    if len(works) != len(work_items):
        raise ValueError(
            "Duplicate work ID in profile."
        )

    facts = {}

    for work in work_items:
        for fact in work.get(
            "facts", []
        ):
            fact_id = fact.get("id")

            if (
                not fact_id
                or fact_id in facts
            ):
                raise ValueError(
                    "Invalid or duplicate "
                    "profile fact ID."
                )

            facts[fact_id] = (
                work["id"],
                str(
                    fact.get("description") or ""
                ),
            )

    if selected_set - set(facts):
        raise ValueError(
            "Snapshot references facts "
            "absent from master profile."
        )

    # Step 3: Validate structured resume.
    resume = ResumeDocument.model_validate(
        snapshot["resume_document"]
    )

    approved_ids = [
        entry.work_id
        for entry in resume.entries
    ]

    if len(approved_ids) != len(
        set(approved_ids)
    ):
        raise ValueError(
            "Duplicate approved ResumeDocument "
            "work IDs."
        )

    for entry in resume.entries:
        work = works.get(
            entry.work_id
        )

        if work is None:
            raise ValueError(
                "Unknown approved work ID: "
                f"{entry.work_id}"
            )

        category = str(
            work.get("category") or ""
        ).lower()

        expected_section = (
            "project"
            if category == "project"
            else "experience"
            if category in {
                "job", "internship"
            }
            else None
        )

        if entry.section != expected_section:
            raise ValueError(
                "Section/category mismatch "
                f"for {entry.work_id}."
            )

        for bullet in entry.bullets:
            fact = facts.get(
                bullet.fact_id,
                (None,),
            )

            if (
                bullet.fact_id
                not in selected_set
                or fact[0] != entry.work_id
            ):
                raise ValueError(
                    "Unsupported fact ownership: "
                    f"{entry.work_id}/"
                    f"{bullet.fact_id}"
                )

    # Step 4: Read actual assembled DOCX.
    document = Document(source)
    paragraphs = document.paragraphs

    warnings = []

    if document.tables:
        warnings.append(
            "DOCX contains tables; headings/bullets "
            "inside tables require manual verification."
        )

    company_use = Counter(
        _normalize(
            str(
                works[work_id].get(
                    "organization"
                ) or ""
            )
        )
        for work_id in approved_ids
        if works[work_id].get(
            "organization"
        )
    )

    entries: list[EntryCoverage] = []
    errors: list[str] = []

    # Step 5: Verify every approved entry.
    for entry in resume.entries:
        work = works[entry.work_id]

        company = _normalize(
            str(
                work.get(
                    "organization"
                ) or ""
            )
        )

        allow_company = (
            bool(company)
            and company_use[company] == 1
        )

        candidates = _candidate_titles(
            work,
            allow_company_only=allow_company,
        )

        positions = _matching_headings(
            paragraphs,
            candidates,
        )

        check = EntryCoverage(
            work_id=entry.work_id,
            section=entry.section,
            matched_heading=(
                paragraphs[positions[0]].text
                if len(positions) == 1
                else None
            ),
            heading_count=len(positions),
            expected_bullets=len(
                entry.bullets
            ),
        )

        if not positions:
            check.notes.append(
                "No confidently matched heading; "
                "verify template naming/mapping."
            )

            errors.append(
                f"{entry.work_id}: approved "
                "heading not located."
            )

        elif len(positions) > 1:
            check.notes.append(
                "Multiple matching headings; "
                "possible duplicate or "
                "ambiguous employer label."
            )

            errors.append(
                f"{entry.work_id}: duplicate/"
                "ambiguous headings."
            )

        else:
            index = positions[0]

            heading = _normalize(
                _heading_text(
                    paragraphs[index].text
                )
            )

            company_only = (
                bool(company)
                and heading == company
            )

            if company_only:
                check.notes.append(
                    "Company-only heading: verify "
                    "role designation before "
                    "final export."
                )

            actual = _adjacent_bullets(
                paragraphs,
                index,
            )

            expected = [
                _normalize(bullet.text)
                for bullet in entry.bullets
            ]

            check.matched_bullets = sum(
                1
                for a, b in zip(
                    actual,
                    expected,
                )
                if a == b
            )

            # Order and exact bullet ownership
            # must match the approved document.
            for position, bullet in enumerate(
                entry.bullets
            ):
                if (
                    position >= len(actual)
                    or actual[position]
                    != expected[position]
                ):
                    check.missing_fact_ids.append(
                        bullet.fact_id
                    )

            if len(actual) > len(expected):
                check.extra_bullets = actual[
                    len(expected):
                ]

            if (
                check.missing_fact_ids
                or check.extra_bullets
            ):
                errors.append(
                    f"{entry.work_id}: approved "
                    "bullets missing, reordered "
                    "or extra."
                )

            elif company_only:
                check.status = "review"

            else:
                check.status = "pass"

        entries.append(check)

    # Step 6: Identify selected facts omitted
    # by the Resume Writer.
    jd_provided = bool(
        job_description
        and job_description.strip()
    )

    terms = _jd_terms(
        job_description or ""
    )

    if not jd_provided:
        warnings.append(
            "No job description supplied; "
            "relevance cannot be assessed."
        )

    omitted_selected = []
    hints = []

    used_in_resume = {
        bullet.fact_id
        for entry in resume.entries
        for bullet in entry.bullets
    }

    for fact_id, (
        work_id,
        description,
    ) in facts.items():

        if fact_id in used_in_resume:
            continue

        matches = sorted(
            terms & _jd_terms(
                description
            )
        )

        if fact_id in selected_set:
            omitted_selected.append(
                OmittedFact(
                    work_id=work_id,
                    fact_id=fact_id,
                    source_fact=description,
                    selected_by_retriever=True,
                    jd_term_matches=matches,
                    reason=(
                        "Selected by retriever but "
                        "omitted by approved "
                        "ResumeDocument; needs "
                        "relevance review."
                    ),
                )
            )

        elif jd_provided and matches:
            hints.append(
                OmittedFact(
                    work_id=work_id,
                    fact_id=fact_id,
                    source_fact=description,
                    selected_by_retriever=False,
                    jd_term_matches=matches,
                    reason=(
                        "Unselected profile fact has "
                        "JD term overlap; informational "
                        "hint, not proof of relevance."
                    ),
                )
            )

    hints.sort(
        key=lambda item: (
            -len(item.jd_term_matches),
            item.work_id,
            item.fact_id,
        )
    )

    # Step 7: Detect possible old template entries.
    # Detection never authorizes deletion.
    retained = []
    approved = set(approved_ids)

    for work in work_items:
        if work["id"] in approved:
            continue

        candidates = _candidate_titles(
            work,
            allow_company_only=False,
        )

        positions = _matching_headings(
            paragraphs,
            candidates,
        )

        for index in positions:
            retained.append(
                RetainedTemplateEntry(
                    work_id=work["id"],
                    heading=_heading_text(
                        paragraphs[index].text
                    ),
                )
            )

    if omitted_selected:
        warnings.append(
            f"{len(omitted_selected)} selected facts "
            "were not used in approved resume; "
            "manual relevance review."
        )

    if retained:
        warnings.append(
            f"{len(retained)} template-only entry "
            "candidates found; do not delete "
            "without review."
        )

    # Step 8: Confirm DOCX was never changed.
    if (
        sha256(
            source.read_bytes()
        ).hexdigest()
        != source_hash
    ):
        raise ValueError(
            "Source DOCX changed during "
            "read-only audit."
        )

    return ResumeContentAudit(
        source_path=str(source),
        snapshot_path=str(
            snapshot_file
        ),
        source_sha256=source_hash,
        approved_work_ids=approved_ids,
        entries=entries,
        omitted_selected_facts=omitted_selected,
        potentially_relevant_unselected_facts=(
            hints[:15]
        ),
        retained_template_entries=retained,
        jd_terms=sorted(terms),
        jd_relevance_reviewed=jd_provided,
        approved_content_complete=(
            not errors
            and all(
                item.status in {
                    "pass", "review"
                }
                for item in entries
            )
        ),
        errors=errors,
        warnings=warnings,
        ready_for_final_export=False,
    )
