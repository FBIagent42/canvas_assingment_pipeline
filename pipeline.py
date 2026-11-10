from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


HEADERS = [
    "Course",
    "Assignment",
    "Due At",
    "Points Possible",
    "Status",
    "Submitted At",
    "Canvas URL",
]
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def canvas_base_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("CANVAS_BASE_URL must be an HTTPS Canvas site URL.")
    return value.rstrip("/")


def iter_canvas_pages(
    session: requests.Session,
    url: str,
    base_url: str,
    params: dict[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    allowed_host = urlparse(base_url).netloc.lower()
    next_url: str | None = url

    while next_url:
        parsed = urlparse(next_url)
        if parsed.scheme != "https" or parsed.netloc.lower() != allowed_host:
            raise ValueError("Canvas pagination returned a URL outside the Canvas site.")

        response = session.get(next_url, params=params, timeout=30)
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
            raise ValueError("Canvas API returned an unexpected paginated response.")

        yield from page
        next_link = response.links.get("next", {}).get("url")
        next_url = urljoin(next_url, next_link) if next_link else None
        params = None


def fetch_assignments(
    session: requests.Session, base_url: str
) -> list[dict[str, Any]]:
    courses_url = f"{base_url}/api/v1/courses"
    courses = iter_canvas_pages(
        session,
        courses_url,
        base_url,
        params={"enrollment_state": "active", "per_page": "100"},
    )
    assignments: list[dict[str, Any]] = []

    for course in courses:
        course_id = course.get("id")
        if course_id is None:
            raise ValueError("Canvas returned a course without an ID.")
        course_name = str(course.get("name") or course.get("course_code") or course_id)
        assignments_url = f"{base_url}/api/v1/courses/{course_id}/assignments"
        course_assignments = iter_canvas_pages(
            session,
            assignments_url,
            base_url,
            params={"include[]": "submission", "per_page": "100"},
        )
        for assignment in course_assignments:
            if assignment.get("published") is False:
                continue
            assignments.append(
                {
                    "course": course_name,
                    "assignment": assignment,
                }
            )

    return assignments


def submission_status(assignment: dict[str, Any]) -> tuple[str, str]:
    submission = assignment.get("submission") or {}
    if submission.get("missing"):
        status = "Missing"
    elif submission.get("submitted_at"):
        status = "Submitted"
    else:
        status = "Not submitted"
    return status, str(submission.get("submitted_at") or "")


def due_sort_key(item: dict[str, Any]) -> tuple[int, datetime, str, str]:
    assignment = item["assignment"]
    due_at = assignment.get("due_at")
    if not due_at:
        due = datetime.max.replace(tzinfo=timezone.utc)
        has_no_due_date = 1
    else:
        due = datetime.fromisoformat(str(due_at).replace("Z", "+00:00"))
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        due = due.astimezone(timezone.utc)
        has_no_due_date = 0
    return (
        has_no_due_date,
        due,
        item["course"].casefold(),
        str(assignment.get("name") or "").casefold(),
    )


def sheet_values(assignments: list[dict[str, Any]]) -> list[list[str]]:
    values = [HEADERS]
    for item in sorted(assignments, key=due_sort_key):
        assignment = item["assignment"]
        status, submitted_at = submission_status(assignment)
        values.append(
            [
                item["course"],
                str(assignment.get("name") or ""),
                str(assignment.get("due_at") or ""),
                ""
                if assignment.get("points_possible") is None
                else str(assignment["points_possible"]),
                status,
                submitted_at,
                str(assignment.get("html_url") or ""),
            ]
        )
    return values


def refresh_google_sheet(
    spreadsheet_id: str,
    tab_title: str,
    service_account_json: str,
    assignments: list[dict[str, Any]],
) -> None:
    service_account_info = json.loads(service_account_json)
    if not isinstance(service_account_info, dict):
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON must contain a JSON object.")
    credentials = Credentials.from_service_account_info(
        service_account_info, scopes=[SHEETS_SCOPE]
    )
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    escaped_title = tab_title.replace("'", "''")
    range_name = f"'{escaped_title}'!A:G"
    values = sheet_values(assignments)

    sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        body={},
    ).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"'{escaped_title}'!A1",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def main() -> None:
    base_url = canvas_base_url(required_env("CANVAS_BASE_URL"))
    canvas_token = required_env("CANVAS_API_TOKEN")
    spreadsheet_id = required_env("GOOGLE_SHEET_ID")
    service_account_json = required_env("GOOGLE_SERVICE_ACCOUNT_JSON")
    tab_title = os.environ.get("CANVAS_SHEET_TAB", "").strip() or "Assignments"

    with requests.Session() as session:
        session.headers.update(
            {
                "Authorization": f"Bearer {canvas_token}",
                "Accept": "application/json",
            }
        )
        assignments = fetch_assignments(session, base_url)

    refresh_google_sheet(
        spreadsheet_id,
        tab_title,
        service_account_json,
        assignments,
    )
    print(f"Refreshed the Google Sheet with {len(assignments)} assignments.")


if __name__ == "__main__":
    main()
