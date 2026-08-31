"""List all Airtable rows — Name and Input fields — for duplicate checking."""

import sys
import os

# Ensure project root is on the path so batch/airtable.py can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from batch.airtable import get_all_rows, row_name, row_input, row_status

rows = get_all_rows()
print(f"Total rows: {len(rows)}\n")
print(f"{'#':<4} {'Name':<35} {'Status':<22} Input")
print(f"{'─'*4} {'─'*35} {'─'*22} {'─'*60}")

for i, row in enumerate(rows, 1):
    name = row_name(row)
    status = row_status(row)
    raw_input = row_input(row)
    # Show first 80 chars of input on one line
    short_input = raw_input.replace("\n", " ")[:80]
    if len(raw_input) > 80:
        short_input += "..."
    print(f"{i:<4} {name:<35} {status:<22} {short_input}")
