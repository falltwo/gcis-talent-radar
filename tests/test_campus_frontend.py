"""Exercise the actual campus controller with deterministic API/DOM/map doubles."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for frontend behavior checks")
class CampusFrontendTests(unittest.TestCase):
    def run_case(self, name):
        result = subprocess.run(
            [shutil.which("node"), str(Path(__file__).with_name("campus_frontend_harness.cjs")), name],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_api_coordinates_are_not_generated_from_the_origin(self):
        self.run_case("actual_api_coordinates")

    def test_changed_location_and_exit_discard_late_responses(self):
        self.run_case("stale_request_and_exit")

    def test_unavailable_source_can_be_retried_without_demo_fallback(self):
        self.run_case("unavailable_then_retry")

    def test_empty_results_and_invalid_radius_do_not_draw_campuses(self):
        self.run_case("empty_and_radius_validation")

    def test_keyword_search_reaches_backend_and_clears_old_results(self):
        self.run_case("keyword_is_an_api_name_search")

    def test_related_toggle_and_explicit_typo_suggestion(self):
        self.run_case("related_toggle_and_suggestions")

    def test_job_title_uses_the_same_field_and_displays_career_sources(self):
        self.run_case("job_search_uses_the_same_field_and_shows_evidence")

    def test_school_panel_shows_only_matched_names_without_enrollment_requests(self):
        self.run_case("school_insights_are_scoped_and_cancelled")

    def test_popup_provenance_and_candidates_do_not_fabricate_campus_relations(self):
        self.run_case("popup_and_candidates_follow_the_origin")

    def test_phone_is_plain_text_and_source_is_in_bottom_source_group(self):
        self.run_case("school_phone_is_plain_text_with_source_below")


if __name__ == "__main__":
    unittest.main()
