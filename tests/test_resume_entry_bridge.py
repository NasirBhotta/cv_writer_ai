
import unittest
from types import SimpleNamespace

from backend.app.models.profile import (
    CareerFact,
    WorkItem,
)
from backend.app.models.resume_document import (
    ResumeBullet,
    ResumeDocument,
    ResumeEntry,
    SkillGroup,
)
from backend.app.models.template_mapping import (
    TemplateMapping,
    TemplateRegion,
)
from backend.app.models.template_report import (
    TemplateBlock,
    TemplateReport,
)
from backend.app.services.template_entry_matcher import (
    map_template_entries,
)
from backend.app.services.resume_entry_bridge import (
    build_document_edit_plan,
)


class EntryBridgeTests(unittest.TestCase):

    def _work(
        self,
        work_id,
        name,
        category,
        fact_ids,
        role=None,
        organization=None,
    ):
        data = {
            "id": work_id,
            "name": name,
            "category": category,
            "description": "Synthetic test work item",
            "technologies": [],
            "facts": [
                CareerFact(
                    id=fact_id,
                    description="Synthetic test fact",
                    skills=[],
                )
                for fact_id in fact_ids
            ],
        }

        # Do not pass None to string-only fields.
        if role is not None:
            data["role"] = role

        if organization is not None:
            data["organization"] = organization

        return WorkItem(**data)

    def setUp(self):
        self.profile = SimpleNamespace(
            work_items=[
                self._work(
                    "crifly_developer",
                    "Crifly — Part-Time Full-Stack Flutter Developer",
                    "job",
                    ["c1"],
                    role="Part-Time Full-Stack Flutter Developer",
                    organization="Crifly",
                ),
                self._work(
                    "crifly_intern",
                    "Crifly — Flutter Developer Internship",
                    "internship",
                    ["c2"],
                    role="Flutter Developer Intern",
                    organization="Crifly",
                ),
                self._work(
                    "brainbee",
                    "BrainBee — AI-Powered Learning Platform",
                    "project",
                    ["b1", "b2"],
                ),
                self._work(
                    "brainbee_research",
                    "BrainBee — Independent AI Learning "
                    "Usability Research Proposal",
                    "project",
                    ["br1"],
                ),
                self._work(
                    "nizaam",
                    "NIZAAM / MobileShop SaaS",
                    "project",
                    ["n1"],
                ),
            ]
        )

        texts = [
            "A NAME",
            "EXPERIENCE",
            "Part-time Full-Stack Flutter Developer — CRIFLY",
            "• Original c1",
            "Full-Stack Flutter Developer Intern — CRIFLY",
            "• Original c2",
            "PROJECTS",
            "BrainBee — AI-Powered Learning Platform",
            "• Original b1",
            "• Original b2",
            "NIZAAM — Retail Management SaaS",
            "• Original n1",
        ]

        self.report = TemplateReport(
            filename="synthetic.docx",
            sha256="test-sha",
            blocks=[
                TemplateBlock(
                    block_id=f"body/{index}",
                    text=text,
                    style_name="Normal",
                )
                for index, text in enumerate(texts)
            ],
            section_hints=[],
            layouts=[],
        )

        self.mapping = TemplateMapping(
            template_sha256="test-sha",
            regions=[
                TemplateRegion(
                    section="experience",
                    heading_id="body/1",
                    heading_text="EXPERIENCE",
                    content_block_ids=[
                        "body/2",
                        "body/3",
                        "body/4",
                        "body/5",
                    ],
                ),
                TemplateRegion(
                    section="projects",
                    heading_id="body/6",
                    heading_text="PROJECTS",
                    content_block_ids=[
                        "body/7",
                        "body/8",
                        "body/9",
                        "body/10",
                        "body/11",
                    ],
                ),
            ],
        )

        self.entries = map_template_entries(
            self.report,
            self.mapping,
            self.profile.work_items,
        )

    def _doc(self, *entries):
        # FIX: ResumeDocument.summary requires 40+ chars.
        # FIX: At least one SkillGroup is required.
        return ResumeDocument(
            headline="Software Engineer",
            summary=(
                "Software engineer experienced in Flutter, "
                "backend development, and AI-powered "
                "applications."
            ),
            skill_groups=[
                SkillGroup(
                    title="Programming and Frameworks",
                    skills=[
                        "Python",
                        "Dart",
                        "Flutter",
                        "Node.js",
                    ],
                )
            ],
            entries=list(entries),
        )

    def _entry(
        self,
        work_id,
        section,
        *pairs,
    ):
        # ResumeEntry uses "project", singular.
        # TemplateRegion uses "projects", plural.
        # The bridge must translate between them.
        return ResumeEntry(
            work_id=work_id,
            section=section,
            bullets=[
                ResumeBullet(
                    fact_id=fact_id,
                    text=text,
                )
                for fact_id, text in pairs
            ],
        )

    def test_matched_work_ids(self):
        self.assertEqual(
            [
                slot.work_id
                for slot in self.entries.slots
            ],
            [
                "crifly_developer",
                "crifly_intern",
                "brainbee",
                "nizaam",
            ],
        )

        self.assertFalse(
            any(
                slot.needs_review
                for slot in self.entries.slots
            )
        )

    def test_entry_boundaries(self):
        self.assertEqual(
            [
                slot.bullet_block_ids
                for slot in self.entries.slots
            ],
            [
                ["body/3"],
                ["body/5"],
                ["body/8", "body/9"],
                ["body/11"],
            ],
        )

    def test_multiple_roles_do_not_mix(self):
        doc = self._doc(
            self._entry(
                "crifly_intern",
                "experience",
                ("c2", "Tailored intern bullet"),
            ),
            self._entry(
                "crifly_developer",
                "experience",
                ("c1", "Tailored part-time bullet"),
            ),
        )

        result = build_document_edit_plan(
            self.report,
            self.mapping,
            self.entries,
            self.profile,
            doc,
        )

        self.assertIsNotNone(result.plan)

        self.assertEqual(
            {
                edit.block_id: edit.new_text
                for edit in result.plan.edits
            },
            {
                "body/5": "Tailored intern bullet",
                "body/3": "Tailored part-time bullet",
            },
        )

        self.assertTrue(result.preview_only)

    def test_multiple_bullets_ordered(self):
        doc = self._doc(
            self._entry(
                "brainbee",
                "project",
                (
                    "b1",
                    "Implemented textbook-based retrieval.",
                ),
                (
                    "b2",
                    "Developed AI-generated quiz features.",
                ),
            )
        )

        result = build_document_edit_plan(
            self.report,
            self.mapping,
            self.entries,
            self.profile,
            doc,
        )

        self.assertEqual(
            [
                edit.block_id
                for edit in result.plan.edits
            ],
            ["body/8", "body/9"],
        )

    def test_bullet_count_mismatch_rejects(self):
        doc = self._doc(
            self._entry(
                "brainbee",
                "project",
                (
                    "b1",
                    "Only one generated bullet.",
                ),
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "bullet count differs",
        ):
            build_document_edit_plan(
                self.report,
                self.mapping,
                self.entries,
                self.profile,
                doc,
            )

    def test_invalid_fact_rejects(self):
        doc = self._doc(
            self._entry(
                "brainbee",
                "project",
                (
                    "c1",
                    "Incorrect work item fact.",
                ),
                (
                    "b2",
                    "Correct BrainBee project fact.",
                ),
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "unsupported fact_id",
        ):
            build_document_edit_plan(
                self.report,
                self.mapping,
                self.entries,
                self.profile,
                doc,
            )

    def test_selected_facts_rejects_unselected(self):
        doc = self._doc(
            self._entry(
                "brainbee",
                "project",
                (
                    "b1",
                    "This fact was selected.",
                ),
                (
                    "b2",
                    "This fact was not selected.",
                ),
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "unsupported fact_id",
        ):
            build_document_edit_plan(
                self.report,
                self.mapping,
                self.entries,
                self.profile,
                doc,
                allowed_fact_ids={"b1"},
            )

    def test_partial_omits_unsafe(self):
        doc = self._doc(
            self._entry(
                "brainbee",
                "project",
                (
                    "b1",
                    "Only one BrainBee bullet.",
                ),
            ),
            self._entry(
                "nizaam",
                "project",
                (
                    "n1",
                    "A valid NIZAAM update.",
                ),
            ),
        )

        result = build_document_edit_plan(
            self.report,
            self.mapping,
            self.entries,
            self.profile,
            doc,
            allow_partial=True,
        )

        self.assertIsNotNone(result.plan)

        self.assertEqual(
            len(result.plan.edits),
            1,
        )

        self.assertEqual(
            result.plan.edits[0].block_id,
            "body/11",
        )

        self.assertEqual(
            len(result.skipped),
            1,
        )

    def test_review_blocks_project(self):
        self.mapping.regions[1].needs_review = True

        entries = map_template_entries(
            self.report,
            self.mapping,
            self.profile.work_items,
        )

        doc = self._doc(
            self._entry(
                "brainbee",
                "project",
                (
                    "b1",
                    "First reviewed bullet.",
                ),
                (
                    "b2",
                    "Second reviewed bullet.",
                ),
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "no unique approved",
        ):
            build_document_edit_plan(
                self.report,
                self.mapping,
                entries,
                self.profile,
                doc,
            )

    def test_hash_mismatch(self):
        self.entries.template_sha256 = "different"

        doc = self._doc(
            self._entry(
                "brainbee",
                "project",
                (
                    "b1",
                    "First validated bullet.",
                ),
                (
                    "b2",
                    "Second validated bullet.",
                ),
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "different template",
        ):
            build_document_edit_plan(
                self.report,
                self.mapping,
                self.entries,
                self.profile,
                doc,
            )

    def test_unmatched_heading_review(self):
        self.report.blocks[7].text = (
            "UNRELATED PROJECT XYZ"
        )

        entries = map_template_entries(
            self.report,
            self.mapping,
            self.profile.work_items,
        )

        self.assertIsNone(
            entries.slots[2].work_id
        )

        self.assertTrue(
            entries.slots[2].needs_review
        )


if __name__ == "__main__":
    unittest.main()
