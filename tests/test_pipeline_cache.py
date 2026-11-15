
import os
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.services.pipeline_cache import (
    load_cached,
    save_cached,
)


class PipelineCacheTests(unittest.TestCase):

    def test_save_and_load(self):
        with patch.dict(
            os.environ,
            {"RESUME_CACHE_ENABLED": "1"},
        ):
            with TemporaryDirectory() as folder:
                cache_dir = Path(folder)

                inputs = {
                    "jd": "Flutter Engineer",
                }

                result = {
                    "required_skills": ["Flutter", "Dart"],
                }

                self.assertIsNone(
                    load_cached(
                        "jd_analysis",
                        inputs,
                        cache_dir,
                    )
                )

                self.assertTrue(
                    save_cached(
                        "jd_analysis",
                        inputs,
                        result,
                        cache_dir,
                    )
                )

                loaded = load_cached(
                    "jd_analysis",
                    inputs,
                    cache_dir,
                )

                self.assertEqual(loaded, result)

    def test_inputs_invalidate_cache(self):
        with patch.dict(
            os.environ,
            {"RESUME_CACHE_ENABLED": "1"},
        ):
            with TemporaryDirectory() as folder:
                cache_dir = Path(folder)

                old_inputs = {
                    "jd": "Flutter Engineer",
                    "profile_version": 1,
                }

                new_inputs = {
                    "jd": "Flutter Engineer",
                    "profile_version": 2,
                }

                save_cached(
                    "selection",
                    old_inputs,
                    ["fact_1"],
                    cache_dir,
                )

                self.assertIsNone(
                    load_cached(
                        "selection",
                        new_inputs,
                        cache_dir,
                    )
                )

    def test_corrupt_cache_is_ignored(self):
        with patch.dict(
            os.environ,
            {"RESUME_CACHE_ENABLED": "1"},
        ):
            with TemporaryDirectory() as folder:
                cache_dir = Path(folder)
                inputs = {"jd": "AI Engineer"}

                save_cached(
                    "jd_analysis",
                    inputs,
                    {"job_title": "AI Engineer"},
                    cache_dir,
                )

                cache_file = next(
                    cache_dir.glob("*.json")
                )

                cache_file.write_text(
                    "not-valid-json",
                    encoding="utf-8",
                )

                self.assertIsNone(
                    load_cached(
                        "jd_analysis",
                        inputs,
                        cache_dir,
                    )
                )

    def test_disabled_cache(self):
        with TemporaryDirectory() as folder:
            cache_dir = Path(folder)
            inputs = {"jd": "Python Engineer"}

            with patch.dict(
                os.environ,
                {"RESUME_CACHE_ENABLED": "0"},
            ):
                saved = save_cached(
                    "jd_analysis",
                    inputs,
                    {"title": "Python Engineer"},
                    cache_dir,
                )

                loaded = load_cached(
                    "jd_analysis",
                    inputs,
                    cache_dir,
                )

                self.assertFalse(saved)
                self.assertIsNone(loaded)


if __name__ == "__main__":
    unittest.main()
