import unittest

from app.agents.models import IncidentMessage
from app.services.recommendation_service import (
    build_final_recommendation,
    build_incident_recommendation,
)


class RecommendationServiceTests(unittest.TestCase):
    def test_unauthorized_request_recommends_auth_review_without_weakening_auth(self):
        message = IncidentMessage(
            incident_id=1,
            sentry_issue_id="issue-1",
            title="Bogus backend request observed",
            culprit="app.main.me",
            repo_full_name="owner/repo",
            error_type="bogus_backend_request",
            request_method="GET",
            request_path="/me",
            status_code=401,
        )

        recommendation = build_incident_recommendation(message)

        self.assertIn("authentication dependency or middleware", recommendation)
        self.assertIn("authenticated and unauthenticated requests", recommendation)
        self.assertIn("Do not weaken authentication", recommendation)

    def test_final_recommendation_contains_finding_actions_and_files(self):
        result = build_final_recommendation(
            suspected_root_cause="GET /me returned 401",
            recommendation="Review authentication middleware.",
            files_to_inspect=["app/main.py"],
        )

        self.assertIn("Observed finding", result)
        self.assertIn("What the system needs", result)
        self.assertIn("app/main.py", result)


if __name__ == "__main__":
    unittest.main()
