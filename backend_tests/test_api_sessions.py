
import unittest
from backend.app import create_app


class FakeModelService:
    def health(self):
        return {"ready": True}


class TestAPISessions(unittest.TestCase):

    def setUp(self):
        self.app = create_app(
            {"TESTING": True},
            model_service=FakeModelService()
        )

    def test_users_have_separate_transcripts(self):
        user_a = self.app.test_client()
        user_b = self.app.test_client()

        # User A adds letter A
        response_a = user_a.post(
            "/api/add-letter",
            json={"letter": "A"}
        )
        self.assertEqual(response_a.status_code, 200)

        # User B should start with an empty transcript
        response_b = user_b.get("/api/transcript")
        self.assertEqual(response_b.status_code, 200)
        self.assertEqual(
            response_b.get_json()["transcript"], ""
        )

        # User B adds letter B
        user_b.post(
            "/api/add-letter",
            json={"letter": "B"}
        )

        # Each user should have their own transcript
        self.assertEqual(
            user_a.get("/api/transcript").get_json()["transcript"],
            "A"
        )
        self.assertEqual(
            user_b.get("/api/transcript").get_json()["transcript"],
            "B"
        )


if __name__ == "__main__":
    unittest.main()

