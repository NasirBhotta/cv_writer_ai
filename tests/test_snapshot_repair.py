
import unittest

from backend.app.services.snapshot_repair import (
    repair_snapshot_bullets,
)


class SnapshotRepairTests(unittest.TestCase):

    def setUp(self):
        self.profile = {
            "work_items": [
                {
                    "id": "brainbee",
                    "facts": [
                        {
                            "id": "brainbee_flutter",
                            "description": (
                                "Developed Flutter interfaces "
                                "connected to backend APIs."
                            ),
                        }
                    ],
                },
                {
                    "id": "recruitflow",
                    "facts": [
                        {
                            "id": "recruitflow_fact_01",
                            "description": (
                                "Implemented Gmail and PDF "
                                "parsing into candidate profiles."
                            ),
                        }
                    ],
                },
            ]
        }

        self.snapshot = {
            "profile_sha256": "a" * 64,
            "quality_passed": False,
            "selected_fact_ids": [
                "brainbee_flutter",
                "recruitflow_fact_01",
            ],
            "evaluation_feedback": (
                "Unsupported generated claims."
            ),
            "resume_document": {
                "entries": [
                    {
                        "work_id": "brainbee",
                        "bullets": [
                            {
                                "fact_id": "brainbee_flutter",
                                "text": (
                                    "Claim with unsupported details"
                                ),
                            }
                        ],
                    },
                    {
                        "work_id": "recruitflow",
                        "bullets": [
                            {
                                "fact_id": "recruitflow_fact_01",
                                "text": (
                                    "Used an unsupported tool"
                                ),
                            }
                        ],
                    },
                ]
            },
        }

    def repair(self, fact_ids=None):
        return repair_snapshot_bullets(
            self.snapshot,
            self.profile,
            profile_sha256="a" * 64,
            fact_ids=(
                fact_ids
                if fact_ids is not None
                else [
                    "brainbee_flutter",
                    "recruitflow_fact_01",
                ]
            ),
        )

    def test_repairs_both_bullets(self):
        candidate, changes = self.repair()

        self.assertEqual(len(changes), 2)
        self.assertFalse(candidate["quality_passed"])

        self.assertEqual(
            candidate["run_status"],
            "needs_revalidation",
        )

        self.assertEqual(
            candidate["resume_document"]
            ["entries"][0]["bullets"][0]["text"],
            self.profile["work_items"][0]
            ["facts"][0]["description"],
        )

    def test_original_snapshot_is_unchanged(self):
        original_text = (
            self.snapshot["resume_document"]
            ["entries"][0]["bullets"][0]["text"]
        )

        self.repair()

        self.assertEqual(
            self.snapshot["resume_document"]
            ["entries"][0]["bullets"][0]["text"],
            original_text,
        )

    def test_wrong_profile_hash_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "SHA-256",
        ):
            repair_snapshot_bullets(
                self.snapshot,
                self.profile,
                profile_sha256="b" * 64,
                fact_ids=["brainbee_flutter"],
            )

    def test_unselected_fact_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "not selected",
        ):
            self.repair(["missing_fact"])

    def test_missing_bullet_rejected(self):
        self.snapshot["resume_document"][
            "entries"
        ][0]["bullets"] = []

        with self.assertRaisesRegex(
            ValueError,
            "not present",
        ):
            self.repair(["brainbee_flutter"])

    def test_wrong_work_id_rejected(self):
        self.snapshot["resume_document"][
            "entries"
        ][0]["work_id"] = "recruitflow"

        with self.assertRaisesRegex(
            ValueError,
            "does not belong",
        ):
            self.repair(["brainbee_flutter"])

    def test_duplicate_target_rejected(self):
        with self.assertRaisesRegex(
            ValueError,
            "unique",
        ):
            self.repair([
                "brainbee_flutter",
                "brainbee_flutter",
            ])

    def test_passed_snapshot_not_rewritten(self):
        self.snapshot["quality_passed"] = True

        with self.assertRaisesRegex(
            ValueError,
            "failed",
        ):
            self.repair()


if __name__ == "__main__":
    unittest.main()
