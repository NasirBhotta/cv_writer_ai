
import unittest

from backend.app.services.career_validator import (
    _company_name,
    _professional_section,
    validate_resume_draft,
)


CONTEXT = {
    "candidate": {
        "name": "Test Candidate",
        "skills": ["Flutter"],
    },
    "work_items": [
        {
            "id": "crifly_developer",
            "category": "job",
            "name": (
                "Crifly — Part-Time "
                "Full-Stack Flutter Developer"
            ),
            "organization": "Crifly",
            "role": (
                "Part-Time Full-Stack "
                "Flutter Developer"
            ),
        },
        {
            "id": "crifly_intern",
            "category": "internship",
            "name": (
                "Crifly — Flutter "
                "Developer Internship"
            ),
            "organization": "Crifly",
            "role": "Flutter Developer Intern",
        },
        {
            "id": "glowsims_intern",
            "category": "internship",
            "name": (
                "Glowsims — Mobile App "
                "Development Internship"
            ),
            "organization": "Glowsims",
            "role": "Mobile App Development Intern",
        },
    ],
}


PREFIX = (
    "# Test Candidate\n"
    "## Technical Skills\n"
    "- Flutter\n"
    "## Professional Experience\n"
)

SUFFIX = (
    "\n## Education\n"
    "BS Computer Science\n"
)


def make_draft(experience: str) -> str:
    return PREFIX + experience + SUFFIX


class CareerValidatorTests(unittest.TestCase):

    def test_both_crifly_roles_present(self):
        experience = (
            "### Crifly — Part-Time "
            "Full-Stack Flutter Developer\n"
            "- Developed Flutter screens.\n"
            "### Crifly — Flutter Developer Intern\n"
            "- Supported backend integration.\n"
            "### Glowsims — Mobile App Development Intern\n"
            "- Improved LMS APIs.\n"
        )

        errors = validate_resume_draft(
            make_draft(experience),
            CONTEXT,
        )

        self.assertEqual(errors, [])

    def test_only_nonintern_crifly_role(self):
        experience = (
            "### Crifly — Part-Time "
            "Full-Stack Flutter Developer\n"
            "- Built Flutter applications.\n"
            "### Glowsims — Mobile App Development Intern\n"
            "- Improved API performance.\n"
        )

        errors = validate_resume_draft(
            make_draft(experience),
            CONTEXT,
        )

        self.assertEqual(errors, [])

    def test_missing_internship_designation(self):
        experience = (
            "### Crifly — Part-Time "
            "Full-Stack Flutter Developer\n"
            "- Developed applications.\n"
            "### Glowsims — Mobile App Development\n"
            "- Improved backend APIs.\n"
        )

        errors = validate_resume_draft(
            make_draft(experience),
            CONTEXT,
        )

        self.assertIn(
            "Internship designation missing for glowsims.",
            errors,
        )

    def test_ambiguous_crifly_role(self):
        experience = (
            "### Crifly — Flutter Developer\n"
            "- Developed applications.\n"
            "### Glowsims — Mobile App Development Intern\n"
            "- Supported APIs.\n"
        )

        errors = validate_resume_draft(
            make_draft(experience),
            CONTEXT,
        )

        self.assertTrue(
            any(
                "Ambiguous professional designation "
                "for crifly" in error
                for error in errors
            )
        )

    def test_internship_omission_is_not_mislabeling(self):
        experience = (
            "### Crifly — Part-Time "
            "Full-Stack Flutter Developer\n"
            "- Built commercial mobile products.\n"
            "### Glowsims — Mobile App Development Intern\n"
            "- Improved backend performance.\n"
        )

        errors = validate_resume_draft(
            make_draft(experience),
            CONTEXT,
        )

        self.assertNotIn(
            "Internship designation missing for crifly.",
            errors,
        )

    def test_subheadings_remain_in_section(self):
        experience = (
            "### Glowsims — Mobile App Development Intern\n"
            "- Optimized LMS APIs.\n"
        )

        section = _professional_section(
            make_draft(experience)
        )

        self.assertIn(
            "### Glowsims",
            section,
        )

    def test_company_name_from_em_dash(self):
        company = _company_name(
            {
                "name": (
                    "Crifly — Flutter Developer Intern"
                )
            }
        )

        self.assertEqual(company, "Crifly")

    def test_unknown_url_still_rejected(self):
        experience = (
            "### Crifly — Part-Time "
            "Full-Stack Flutter Developer\n"
            "- Built apps at https://fake.example/work\n"
            "### Glowsims — Mobile App Development Intern\n"
            "- Improved APIs.\n"
        )

        errors = validate_resume_draft(
            make_draft(experience),
            CONTEXT,
        )

        self.assertTrue(
            any(
                "URL not found in career evidence"
                in error
                for error in errors
            )
        )


if __name__ == "__main__":
    unittest.main()
