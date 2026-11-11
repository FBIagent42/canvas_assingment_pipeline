from __future__ import annotations

import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build


SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
DIGEST_DAYS = 7
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
REQUIRED_COLUMNS = {"Course", "Assignment", "Due At", "Status", "Canvas URL"}


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def read_sheet_assignments(
    spreadsheet_id: str,
    tab_title: str,
    service_account_json: str,
) -> list[dict[str, str]]:
    service_account_info = json.loads(service_account_json)
    if not isinstance(service_account_info, dict):
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON must contain a JSON object.")

    credentials = Credentials.from_service_account_info(
        service_account_info,
        scopes=[SHEETS_SCOPE],
    )
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    escaped_title = tab_title.replace("'", "''")
    response = (
        sheets.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=f"'{escaped_title}'!A:G")
        .execute()
    )
    values = response.get("values", [])
    if not values:
        raise ValueError(f"The Google Sheets tab '{tab_title}' is empty.")

    headers = [str(value).strip() for value in values[0]]
    missing_columns = REQUIRED_COLUMNS.difference(headers)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"The Google Sheets tab is missing required columns: {missing}")

    assignments = []
    for row in values[1:]:
        assignments.append(
            {
                header: str(row[index]) if index < len(row) else ""
                for index, header in enumerate(headers)
            }
        )
    return assignments


def parse_due_at(value: str) -> datetime:
    due_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    return due_at.astimezone(timezone.utc)


def upcoming_assignments(
    assignments: list[dict[str, str]],
    now: datetime,
    days: int = DIGEST_DAYS,
) -> list[dict[str, str]]:
    if now.tzinfo is None:
        raise ValueError("now must include a timezone.")
    if days <= 0:
        raise ValueError("days must be greater than zero.")

    start = now.astimezone(timezone.utc)
    end = start + timedelta(days=days)
    upcoming = []

    for assignment in assignments:
        due_at = assignment.get("Due At", "").strip()
        if not due_at or assignment.get("Status", "").strip().casefold() == "submitted":
            continue
        due = parse_due_at(due_at)
        if start <= due < end:
            upcoming.append(assignment)

    return sorted(
        upcoming,
        key=lambda assignment: (
            parse_due_at(assignment["Due At"]),
            assignment.get("Course", "").casefold(),
            assignment.get("Assignment", "").casefold(),
        ),
    )


def format_due_at(value: str) -> str:
    return parse_due_at(value).strftime("%a, %b %d at %I:%M %p UTC")


def build_email_body(
    assignments: list[dict[str, str]], now: datetime
) -> str:
    start = now.astimezone(timezone.utc)
    end = start + timedelta(days=DIGEST_DAYS)
    lines = [
        "Your Canvas assignments due in the next seven days:",
        f"Window: {start:%Y-%m-%d %H:%M} UTC through {end:%Y-%m-%d %H:%M} UTC",
        "",
    ]

    if not assignments:
        lines.append("You have no unsubmitted assignments due in this window.")
        return "\n".join(lines)

    for assignment in assignments:
        lines.extend(
            [
                f"{assignment.get('Course') or 'Unknown course'} — "
                f"{assignment.get('Assignment') or 'Untitled assignment'}",
                f"Due: {format_due_at(assignment['Due At'])}",
                f"Canvas: {assignment.get('Canvas URL') or 'No assignment link provided'}",
                "",
            ]
        )

    return "\n".join(lines).rstrip()


def send_digest(
    sender: str,
    app_password: str,
    recipient: str,
    assignments: list[dict[str, str]],
    now: datetime,
) -> None:
    message = EmailMessage()
    message["Subject"] = "Your upcoming Canvas assignments"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(build_email_body(assignments, now))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(sender, "".join(app_password.split()))
        smtp.send_message(message)


def main() -> None:
    spreadsheet_id = required_env("GOOGLE_SHEET_ID")
    service_account_json = required_env("GOOGLE_SERVICE_ACCOUNT_JSON")
    tab_title = os.environ.get("CANVAS_SHEET_TAB", "").strip() or "Assignments"
    sender = required_env("GMAIL_USERNAME")
    app_password = required_env("GMAIL_APP_PASSWORD")
    recipient = required_env("EMAIL_TO")

    assignments = read_sheet_assignments(
        spreadsheet_id,
        tab_title,
        service_account_json,
    )
    now = datetime.now(timezone.utc)
    digest_assignments = upcoming_assignments(assignments, now)
    send_digest(sender, app_password, recipient, digest_assignments, now)
    print(f"Sent the weekly digest with {len(digest_assignments)} assignments.")


if __name__ == "__main__":
    main()
