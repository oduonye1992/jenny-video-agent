"""Airtable client for the batch production pipeline.

Reads rows from the Batch table, updates fields and status as phases
progress. This is the single interface between the batch pipeline and
Airtable — all other batch code talks to this module, never to the
Airtable API directly.

Environment:
    AIRTABLE_API_KEY — Personal Access Token with schema.bases:read,
                       data.records:read, data.records:write scopes.

The Airtable base and table are supplied through environment variables.
"""

import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Constants ────────────────────────────────────────────────────────────

BASE_ID = os.environ.get("AIRTABLE_BASE_ID", "")
TABLE_ID = os.environ.get("AIRTABLE_TABLE_ID", "")
if not BASE_ID or not TABLE_ID:
    raise RuntimeError(
        "AIRTABLE_BASE_ID and AIRTABLE_TABLE_ID must be set in .env. "
        "Find them in your Airtable URL: airtable.com/{BASE_ID}/{TABLE_ID}"
    )
API_URL = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}"
# Valid statuses (matches the singleSelect choices).
STATUSES = {
    "new",
    "generating_plan",
    "review_plan",
    "approved_plan",
    "needs_reference_photo",
    "generating_frame",
    "review_frame",
    "approved",
    "producing",
    "done",
    "failed",
    "rejected",
}


# ── Auth ─────────────────────────────────────────────────────────────────

def _api_key() -> str:
    key = os.environ.get("AIRTABLE_API_KEY", "")
    if not key:
        raise RuntimeError(
            "AIRTABLE_API_KEY not set. Add it to .env with your Personal Access Token."
        )
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


# ── Core API helpers ─────────────────────────────────────────────────────

def _request(method: str, url: str, **kwargs) -> dict:
    """Make an Airtable API request with retry on rate limit."""
    for attempt in range(1, 4):
        resp = requests.request(method, url, headers=_headers(), **kwargs)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 30))
            print(f"  [airtable] Rate limited, waiting {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json() if resp.text else {}
    raise RuntimeError("Airtable rate limit exceeded after 3 retries")


# ── Read ─────────────────────────────────────────────────────────────────

def get_all_rows() -> list[dict]:
    """Fetch all rows from the Batch table.

    Returns a list of dicts, each with:
        id (str): Airtable record ID
        fields (dict): field name → value
    """
    rows: list[dict] = []
    offset = None

    while True:
        params: dict[str, Any] = {"pageSize": 100}
        if offset:
            params["offset"] = offset
        data = _request("GET", API_URL, params=params)
        for record in data.get("records", []):
            rows.append({
                "id": record["id"],
                "fields": record.get("fields", {}),
            })
        offset = data.get("offset")
        if not offset:
            break

    return rows


def get_rows_by_status(*statuses: str) -> list[dict]:
    """Fetch rows matching any of the given statuses."""
    formula_parts = [f"{{Status}}='{s}'" for s in statuses]
    if len(formula_parts) == 1:
        formula = formula_parts[0]
    else:
        formula = f"OR({','.join(formula_parts)})"

    rows: list[dict] = []
    offset = None

    while True:
        params: dict[str, Any] = {
            "pageSize": 100,
            "filterByFormula": formula,
        }
        if offset:
            params["offset"] = offset
        data = _request("GET", API_URL, params=params)
        for record in data.get("records", []):
            rows.append({
                "id": record["id"],
                "fields": record.get("fields", {}),
            })
        offset = data.get("offset")
        if not offset:
            break

    return rows


def get_row(record_id: str) -> dict:
    """Fetch a single row by record ID."""
    data = _request("GET", f"{API_URL}/{record_id}")
    return {
        "id": data["id"],
        "fields": data.get("fields", {}),
    }


# ── Write ────────────────────────────────────────────────────────────────

def update_row(record_id: str, fields: dict) -> dict:
    """Update fields on a single row.

    Args:
        record_id: Airtable record ID (e.g. "recXXXXXX")
        fields: dict of field name → value. Only the fields you pass
                are updated; others are left unchanged.

    Returns the updated record.
    """
    data = _request("PATCH", f"{API_URL}/{record_id}", json={
        "fields": fields,
        "typecast": True,
    })
    return {
        "id": data["id"],
        "fields": data.get("fields", {}),
    }


def update_status(record_id: str, status: str, **extra_fields) -> dict:
    """Update a row's status and optionally other fields.

    Args:
        record_id: Airtable record ID
        status: must be one of STATUSES
        **extra_fields: additional fields to update (e.g. Error="timeout")
    """
    if status not in STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {STATUSES}")
    fields = {"Status": status, **extra_fields}
    return update_row(record_id, fields)


def clear_error(record_id: str) -> dict:
    """Clear the Error field on a row."""
    return update_row(record_id, {"Error": ""})


# ── Attachment helpers ───────────────────────────────────────────────────

def upload_attachment(record_id: str, field_name: str, file_path: str,
                      slug: str = "", filename: str | None = None) -> dict:
    """Upload a single local file as an attachment to an Airtable field.

    Replaces any existing attachments in the field.
    For multiple files, use upload_attachments() instead.

    Files are organized in Supabase as: batch/<slug>/<filename>
    """
    return upload_attachments(record_id, field_name, [file_path], slug,
                              [filename] if filename else None)


def upload_attachments(record_id: str, field_name: str, file_paths: list[str],
                       slug: str = "", filenames: list[str] | None = None) -> dict:
    """Upload multiple local files as attachments to an Airtable field.

    All files appear as thumbnails in the same cell.
    Files are organized in Supabase as: batch/<slug>/<filename>

    Args:
        record_id: Airtable record ID
        field_name: attachment field name (e.g. "Frames")
        file_paths: list of local file paths
        slug: concept slug for folder organization
        filenames: optional override filenames (must match length of file_paths)
    """
    from workflow.adapters._supabase import upload_to_supabase, IMAGE_BUCKET

    attachments = []
    for i, file_path in enumerate(file_paths):
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        fname = (filenames[i] if filenames and i < len(filenames)
                 else os.path.basename(file_path))
        folder = f"batch/{slug}" if slug else "batch"
        remote_path = f"{folder}/{fname}"
        public_url = upload_to_supabase(IMAGE_BUCKET, file_path, remote_path)
        attachments.append({"url": public_url, "filename": fname})

    return update_row(record_id, {field_name: attachments})


def download_attachment(row: dict, field_name: str, dest_path: str) -> str | None:
    """Download the first attachment from a field to a local path.

    Airtable attachments have a temporary signed URL that expires.
    This downloads the file immediately.

    Args:
        row: the row dict (with 'fields')
        field_name: attachment field name (e.g. "Reference Photo")
        dest_path: local path to save the file to

    Returns:
        dest_path if downloaded, None if no attachment exists.
    """
    attachments = row["fields"].get(field_name, [])
    if not attachments:
        return None

    url = attachments[0].get("url", "")
    if not url:
        return None

    resp = requests.get(url)
    resp.raise_for_status()

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(resp.content)

    return dest_path


# ── Push concept to Airtable ─────────────────────────────────────────────

def push_concept(concept_path: str) -> dict:
    """Create a new Airtable row from a local concept folder.

    Reads concept.json and plan.md. The plan is the single artifact that
    contains everything (script, character, shots, prompts, cost).

    Args:
        concept_path: absolute path to the concept folder
            (e.g. outputs/concepts/emotional-distance-20260308/)

    Returns:
        The created Airtable row dict.
    """
    import json

    concept_json_path = os.path.join(concept_path, "concept.json")
    if not os.path.exists(concept_json_path):
        raise FileNotFoundError(f"No concept.json in {concept_path}")

    with open(concept_json_path) as f:
        concept = json.load(f)

    slug = concept.get("slug", "")
    fields: dict[str, Any] = {
        "Name": slug.replace("-", " ").rsplit(" ", 1)[0].title() if slug else "",
        "Slug": slug,
        "Concept Path": os.path.abspath(concept_path),
        "Video Type": concept.get("video_type", ""),
        "Cost Profile": concept.get("profile", ""),
        "Mode": concept.get("mode", "semi-auto"),
        "Status": "review_plan",
    }

    # Read the plan — this is the single source of truth
    plan_path = os.path.join(concept_path, "plan.md")
    if os.path.exists(plan_path):
        with open(plan_path) as f:
            fields["Plan"] = f.read().strip()

    # Create the row
    data = _request("POST", API_URL, json={"fields": fields})
    record = {
        "id": data["id"],
        "fields": data.get("fields", {}),
    }

    # Write the record ID back to concept.json
    concept["airtable_record_id"] = data["id"]
    with open(concept_json_path, "w") as f:
        json.dump(concept, f, indent=2)
        f.write("\n")

    return record


# ── Convenience ──────────────────────────────────────────────────────────

def row_input(row: dict) -> str:
    """Get the raw input text from a row."""
    return row["fields"].get("Input", "").strip()


def row_topic(row: dict) -> str:
    """Get the topic label — from Name field, or first 60 chars of input."""
    name = row["fields"].get("Name", "").strip()
    if name:
        return name
    raw = row_input(row)
    if raw:
        first_line = raw.split("\n")[0][:60]
        return first_line + ("..." if len(raw) > 60 else "")
    return "(no input)"


def row_status(row: dict) -> str:
    """Get the status from a row, with fallback."""
    return row["fields"].get("Status", "new")


def row_video_type(row: dict) -> str:
    """Get the video type. Returns empty string if not set."""
    return row["fields"].get("Video Type", "").strip()


def row_duration(row: dict) -> str:
    """Get duration as raw string. Returns empty string if not set."""
    return row["fields"].get("Duration", "").strip()


def row_profile(row: dict) -> str:
    """Get profile. Returns empty string if not set."""
    return row["fields"].get("Cost Profile", "").strip()


# Fields the user MUST fill before the pipeline processes a row.
# Only Input is truly required — everything else has smart defaults.
REQUIRED_FIELDS = ["Input"]


def row_missing_fields(row: dict) -> list[str]:
    """Return list of required fields that are empty or missing."""
    missing = []
    for field in REQUIRED_FIELDS:
        val = row["fields"].get(field, "")
        if not str(val).strip():
            missing.append(field)
    return missing


def row_mode(row: dict) -> str:
    """Get the mode. Default: semi-auto for batch."""
    return row["fields"].get("Mode", "semi-auto").strip() or "semi-auto"


def row_plan(row: dict) -> str:
    """Get the plan text."""
    return row["fields"].get("Plan", "").strip()


def row_name(row: dict) -> str:
    """Get the display name for a row — Name field, or fallback to topic."""
    name = row["fields"].get("Name", "").strip()
    if name:
        return name
    return row_topic(row)


def print_summary(rows: list[dict]) -> None:
    """Print a status summary table."""
    if not rows:
        print("  No rows found.")
        return

    print(f"  {'#':<4} {'Name':<30} {'Type':<14} {'Status':<22} {'Issues'}")
    print(f"  {'─'*4} {'─'*30} {'─'*14} {'─'*22} {'─'*20}")
    for i, row in enumerate(rows, 1):
        name = row_name(row)[:28]
        vtype = row_video_type(row) or "—"
        status = row_status(row)
        missing = row_missing_fields(row)
        issues = f"missing: {', '.join(missing)}" if missing else ""
        print(f"  {i:<4} {name:<30} {vtype:<14} {status:<22} {issues}")
