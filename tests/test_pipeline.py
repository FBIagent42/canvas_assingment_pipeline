import os
import unittest
from unittest.mock import MagicMock, Mock, patch

from pipeline import due_sort_key, iter_canvas_pages, main, sheet_values


class FakeResponse:
    def __init__(self, data, next_url=None):
        self.data = data
        self.links = {"next": {"url": next_url}} if next_url else {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class PipelineTests(unittest.TestCase):
    def test_canvas_pagination_follows_next_link(self):
        session = MagicMock()
        session.get.side_effect = [
            FakeResponse([{"id": 1}], "https://canvas.example/api/v1/courses?page=2"),
            FakeResponse([{"id": 2}]),
        ]

        result = list(
            iter_canvas_pages(
                session,
                "https://canvas.example/api/v1/courses",
                "https://canvas.example",
                params={"per_page": "100"},
            )
        )

        self.assertEqual(result, [{"id": 1}, {"id": 2}])
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args_list[1].kwargs["params"], None)

    def test_canvas_pagination_rejects_other_hosts(self):
        session = Mock()
        session.get.return_value = FakeResponse(
            [{"id": 1}], "https://attacker.example/collect"
        )

        with self.assertRaisesRegex(ValueError, "outside the Canvas site"):
            list(
                iter_canvas_pages(
                    session,
                    "https://canvas.example/api/v1/courses",
                    "https://canvas.example",
                )
            )
        self.assertEqual(session.get.call_count, 1)

    def test_sheet_values_are_sorted_and_include_submission_state(self):
        assignments = [
            {
                "course": "Algorithms",
                "assignment": {
                    "name": "Later",
                    "due_at": "2026-11-12T10:00:00-07:00",
                    "points_possible": 20,
                    "submission": {"submitted_at": "2026-11-11T09:00:00-07:00"},
                    "html_url": "https://canvas.example/late",
                },
            },
            {
                "course": "Operating Systems",
                "assignment": {
                    "name": "No due date",
                    "due_at": None,
                    "submission": {"missing": True},
                },
            },
            {
                "course": "Algorithms",
                "assignment": {
                    "name": "Sooner",
                    "due_at": "2026-11-11T10:00:00-07:00",
                    "submission": {},
                },
            },
        ]

        result = sheet_values(assignments)

        self.assertEqual(result[0][0], "Course")
        self.assertEqual([row[1] for row in result[1:]], ["Sooner", "Later", "No due date"])
        self.assertEqual(result[1][4], "Not submitted")
        self.assertEqual(result[2][4:6], ["Submitted", "2026-11-11T09:00:00-07:00"])
        self.assertEqual(result[3][4], "Missing")

    def test_assignments_without_due_dates_sort_last(self):
        with_due_date = {
            "course": "Course",
            "assignment": {"due_at": "2026-11-11T10:00:00Z", "name": "A"},
        }
        without_due_date = {
            "course": "Course",
            "assignment": {"due_at": None, "name": "B"},
        }

        self.assertLess(due_sort_key(with_due_date), due_sort_key(without_due_date))

    @patch.dict(
        os.environ,
        {
            "CANVAS_BASE_URL": "https://canvas.example",
            "CANVAS_API_TOKEN": "test-canvas-token",
            "GOOGLE_SHEET_ID": "test-sheet-id",
            "GOOGLE_SERVICE_ACCOUNT_JSON": "{}",
        },
        clear=True,
    )
    @patch("pipeline.refresh_google_sheet")
    @patch("pipeline.fetch_assignments", return_value=[])
    @patch("pipeline.requests.Session")
    def test_main_sends_canvas_token_as_bearer(
        self, session_factory, fetch_assignments_mock, refresh_sheet_mock
    ):
        session = MagicMock()
        session.headers = {}
        session.__enter__.return_value = session
        session_factory.return_value = session

        main()

        scheme, token = session.headers["Authorization"].split(" ", maxsplit=1)
        self.assertEqual(scheme, "Bearer")
        self.assertEqual(token, "test-canvas-token")
        fetch_assignments_mock.assert_called_once()
        refresh_sheet_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
