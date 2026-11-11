# Daily Canvas Assignments

This personal pipeline runs once each morning in GitHub Actions, reads assignments
from your active Canvas courses, and refreshes a Google Sheets tab. It uses the
Canvas REST API and Google Sheets API; it does not need BigQuery or a continuously
running server.

The sheet includes published assignments from active courses, ordered by due date.
It includes past and future work so overdue or missing work is not silently hidden.
Each run replaces the previous snapshot rather than appending duplicate rows.

## Set it up

### 1. Create a private GitHub repository

Create a GitHub account if you do not already have one, then create a **private**
repository for this project. Add the files in this folder to its default branch.
Keeping the repository private is recommended because the workflow is connected
to your personal school account.

If you have Git installed, you can publish the folder from PowerShell after
creating an empty GitHub repository (replace the URL with your repository URL):

```powershell
git init -b main
git add .
git commit-m "Add daily Canvas assignments pipeline"
git remote add origin https://github.com/YOUR-USERNAME/canvas-assignments.git
git push -u origin main 
```

### 2. Create a Canvas API token

In Canvas, open **Account → Settings** and create a new access token. Copy it
when Canvas shows it; treat it like your password and do not put it in a source
file. The token can read only what your Canvas account is permitted to access.
Use an expiration date if your Canvas instance offers one.

Record your Canvas site URL, for example `https://school.instructure.com` (use
your school's actual Canvas URL, without `/login`).

### 3. Set up Google Sheets access

1. Sign in to [Google Cloud Console](https://console.cloud.google.com/) with the
   Google account that will own the sheet.
2. Create a Google Cloud project, then enable the **Google Sheets API** for it.
3. Create a service account in **IAM & Admin → Service Accounts** and create a
   JSON key for that service account. Store the downloaded key securely; never
   commit it to GitHub.
4. Create a Google spreadsheet and add a tab named `Assignments`.
5. Copy the service account's email address and share the spreadsheet with it as
   an **Editor**.
6. Copy the spreadsheet ID from its URL. It is the text between `/d/` and
   `/edit`, such as `https://docs.google.com/spreadsheets/d/<ID>/edit`.

The workflow only needs the Sheets API; it does not deploy a Google Cloud
server. Check your Google Cloud project and API quotas for your account.

### 4. Add repository secrets

In the GitHub repository, open **Settings → Secrets and variables → Actions**.
Add these **repository secrets**:

| Name | Value |
| --- | --- |
| `CANVAS_BASE_URL` | Your Canvas site URL, such as `https://school.instructure.com` |
| `CANVAS_API_TOKEN` | The token created in step 2 |
| `GOOGLE_SHEET_ID` | The ID copied from your spreadsheet URL |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The complete contents of the service account JSON key file |

Optionally add a repository **variable** named `CANVAS_SHEET_TAB` if your tab
is not named `Assignments`.

### 5. Run it once and verify

Push the project files to the repository's default branch. In the repository,
open **Actions → Refresh Canvas assignments → Run workflow** to test it
immediately. A successful run should create a timestamped history in the
workflow run and update the spreadsheet. If it fails, open the run's log; the
step that failed will report the API error.

The scheduled run is set for **14:15 UTC** (about 6:15 a.m. Pacific Standard
Time or 7:15 a.m. Pacific Daylight Time). GitHub scheduled workflows use UTC
and can be delayed during busy periods, so this is a daily best-effort refresh,
not a guaranteed exact-time alert. To change it, edit the `cron` value in
`.github/workflows/daily-assignments.yml`.

## Run locally (optional)

Install the requirements with `python -m pip install -r requirements.txt`, then
set the same environment variables listed above and run `python pipeline.py`.
Do not save real tokens or the service account key in a committed `.env` file.

Run the unit tests with `python -m unittest discover -s tests -v`.

## Weekly email digest

The separate `.github/workflows/weekly-email.yml` workflow runs on Mondays at
15:00 UTC and can also be started manually from the Actions tab. It reads the
latest rows from the `Assignments` tab in Google Sheets; it does not call the
Canvas API. The digest includes assignments with a due date in the next seven
days unless their `Status` is `Submitted`. It groups assignments by course and
sorts each course's assignments by due date. It sends an email even when there
are no matching assignments. Due times in the message are shown in UTC.

The weekly workflow uses the existing `GOOGLE_SHEET_ID` and
`GOOGLE_SERVICE_ACCOUNT_JSON` repository secrets to read the sheet. It also
needs these email secrets:

| Name | Value |
| --- | --- |
| `GMAIL_USERNAME` | The Gmail account used to send the digest |
| `GMAIL_APP_PASSWORD` | An app password for that account (requires 2-Step Verification) |
| `EMAIL_TO` | The address that should receive the digest |

It does not need the Canvas token. If your sheet tab has a different name, set
the repository variable `CANVAS_SHEET_TAB`; otherwise, the workflow uses
`Assignments`. Check whether your school-managed Google account permits app
passwords. GitHub scheduled workflows use UTC and can be delayed during busy
periods.

## Security notes

- Never put Canvas tokens or Google service-account keys in source code, issues,
  logs, or commits. If exposed, revoke and replace them.
- Never put a Gmail app password in source code or logs; revoke and replace it
  if exposed.
- Grant the service account access only to this spreadsheet; do not share the
  key file itself.
- The Canvas token inherits the permissions of your Canvas user account.
- If you no longer want the pipeline, delete the repository secrets and revoke
  the Canvas token, Google service-account key, and Gmail app password.
