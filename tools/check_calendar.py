"""
Google Calendar WFH Checker
-----------------------------
Checks today's Google Calendar events for WFH indicators.
Returns True if today is a WFH day, False otherwise.

WFH detection logic:
- Looks for events with titles containing wfh keywords (case-insensitive)
- Also checks for "office", "onsite", "on-site" to mark as NOT wfh

Setup: requires credentials.json (Google OAuth) in project root.
       On first run, opens a browser to authorize. token.json is saved for future runs.

Usage:
    python tools/check_calendar.py
    python tools/check_calendar.py --date 2026-05-20
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone, timedelta

import httplib2
import requests as requests_lib
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import google_auth_httplib2

load_dotenv()

# SSL bypass for corporate certificate chains.
# _requests_no_ssl is only used for token refresh (single-threaded), so a session is fine.
# Http objects are NOT thread-safe — always create a fresh one per call (see get_calendar_service).
_requests_no_ssl = requests_lib.Session()
_requests_no_ssl.verify = False

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")
TOKEN_PATH = os.path.join(BASE_DIR, "token.json")

WFH_KEYWORDS = {"wfh", "work from home", "working from home", "remote", "home office"}
OFFICE_KEYWORDS = {"office", "onsite", "on-site", "on site", "in office"}


def get_calendar_service():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request(session=_requests_no_ssl))
        else:
            if not os.path.exists(CREDENTIALS_PATH):
                print(f"ERROR: credentials.json not found at {CREDENTIALS_PATH}")
                print("Download it from Google Cloud Console > APIs & Services > Credentials")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            flow.oauth2session.verify = False
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    http = httplib2.Http(disable_ssl_certificate_validation=True)
    authed_http = google_auth_httplib2.AuthorizedHttp(creds, http=http)
    return build("calendar", "v3", http=authed_http)


def check_wfh(target_date: date | None = None) -> bool:
    if target_date is None:
        target_date = date.today()

    service = get_calendar_service()

    # Use local timezone boundaries so that all-day events on adjacent dates
    # (which Google stores as local midnight) don't bleed into the wrong day.
    local_tz = datetime.now().astimezone().tzinfo
    time_min = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=local_tz).isoformat()
    time_max = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=local_tz).isoformat()

    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = events_result.get("items", [])

    if not events:
        print(f"[Calendar] No events found for {target_date}. Defaulting to: NOT WFH")
        return False

    wfh_signals = 0
    office_signals = 0

    for event in events:
        title = event.get("summary", "").lower()
        description = event.get("description", "").lower()
        combined = f"{title} {description}"

        for kw in WFH_KEYWORDS:
            if kw in combined:
                wfh_signals += 1
                print(f"[Calendar] WFH signal in event: '{event.get('summary')}'")
                break

        for kw in OFFICE_KEYWORDS:
            if kw in combined:
                office_signals += 1
                print(f"[Calendar] Office signal in event: '{event.get('summary')}'")
                break

    is_wfh = wfh_signals > 0 and office_signals == 0
    print(f"[Calendar] {target_date} — WFH={is_wfh} (wfh_signals={wfh_signals}, office_signals={office_signals})")
    return is_wfh


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Google Calendar WFH Checker")
    parser.add_argument("--date", help="Date to check (YYYY-MM-DD), defaults to today")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    target = None
    if args.date:
        target = date.fromisoformat(args.date)

    result = check_wfh(target)

    if args.json:
        print(json.dumps({"wfh": result, "date": str(target or date.today())}))
    else:
        status = "WFH day" if result else "NOT a WFH day"
        print(f"\nResult: {status}")
