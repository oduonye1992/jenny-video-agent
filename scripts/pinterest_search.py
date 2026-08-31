"""Pinterest reference photo search via agent-browser.

Usage:
    python scripts/pinterest_search.py "woman car selfie dashboard glow" --limit 8
    python scripts/pinterest_search.py "woman car selfie" --download outputs/concepts/my-concept/reference.png
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse

BROWSER_TIMEOUT = 30


# ── Browser helpers ───────────────────────────────────────────────────────


def _run(cmd: list[str], timeout: int = BROWSER_TIMEOUT) -> str:
    """Run an agent-browser command, return stdout."""
    result = subprocess.run(
        ["agent-browser"] + cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"agent-browser {cmd[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _dismiss_login_modal():
    """Try to dismiss Pinterest's login modal if it appears."""
    try:
        _run(["eval", 'document.querySelector(\'[data-test-id="full-page-signup-close-button"]\')?.click()'])
    except RuntimeError:
        pass


# ── Core ──────────────────────────────────────────────────────────────────

_EXTRACT_JS = """
JSON.stringify(
  Array.from(document.querySelectorAll('img[src*="pinimg"]'))
    .filter(img => /\\/(236x|474x|736x)\\//.test(img.src))
    .map(img => ({
      alt: (img.alt || '').slice(0, 200),
      url: img.src.replace(/\\/\\d+x\\//, '/originals/'),
      thumbnail: img.src,
    }))
)
"""


def search_pinterest(query: str, limit: int = 8, scroll_count: int = 2) -> list[dict]:
    """Search Pinterest and return image results.

    Args:
        query: Search terms (e.g. "woman car selfie dashboard glow").
        limit: Max results to return.
        scroll_count: Number of scroll-downs for lazy loading.

    Returns:
        List of dicts with keys: alt, url, thumbnail.
    """
    url = f"https://www.pinterest.com/search/pins/?q={urllib.parse.quote(query)}"

    print(f"  [pinterest] Searching: {query}", file=sys.stderr)
    try:
        _run(["open", url])
        _run(["wait", "3000"])
        _dismiss_login_modal()

        # Scroll to trigger lazy loading
        for i in range(scroll_count):
            _run(["scroll", "down", "1500"])
            _run(["wait", "2000"])

        # Extract image data
        raw = _run(["eval", _EXTRACT_JS.strip()])

        # agent-browser wraps eval output in quotes — parse the outer string then the JSON
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
        except json.JSONDecodeError:
            print(f"  [pinterest] Failed to parse results: {raw[:200]}", file=sys.stderr)
            return []

        # Deduplicate by URL
        seen = set()
        results = []
        for item in parsed:
            if item["url"] not in seen:
                seen.add(item["url"])
                results.append(item)
            if len(results) >= limit:
                break

        print(f"  [pinterest] Found {len(results)} images", file=sys.stderr)
        return results

    except (RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"  [pinterest] Error: {e}", file=sys.stderr)
        return []
    finally:
        try:
            _run(["close"])
        except (RuntimeError, subprocess.TimeoutExpired):
            pass


def download_image(url: str, output_path: str) -> str | None:
    """Download an image URL to a local path.

    Falls back to 736x thumbnail if originals returns 403.
    Returns the absolute path on success, None on failure.
    """
    import requests

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    for attempt_url in [url, url.replace("/originals/", "/736x/")]:
        try:
            resp = requests.get(attempt_url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            })
            if resp.status_code == 200 and len(resp.content) > 1000:
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                return os.path.abspath(output_path)
        except requests.RequestException:
            continue

    print(f"  [pinterest] Failed to download: {url}", file=sys.stderr)
    return None


def search_and_download(
    query: str,
    limit: int = 8,
    download_path: str | None = None,
    scroll_count: int = 2,
) -> dict:
    """Search Pinterest and optionally download the first result.

    Returns:
        Dict with keys: query, count, results, downloaded.
    """
    results = search_pinterest(query, limit=limit, scroll_count=scroll_count)
    downloaded = None

    if download_path and results:
        downloaded = download_image(results[0]["url"], download_path)
        if downloaded:
            print(f"  [pinterest] Downloaded: {downloaded}", file=sys.stderr)

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "downloaded": downloaded,
    }


# ── CLI ───────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Search Pinterest for reference photos")
    parser.add_argument("query", help="Search terms")
    parser.add_argument("--limit", type=int, default=8, help="Max results (default: 8)")
    parser.add_argument("--download", help="Download first result to this path")
    parser.add_argument("--scroll", type=int, default=2, help="Scroll count for lazy loading (default: 2)")
    args = parser.parse_args()

    result = search_and_download(
        query=args.query,
        limit=args.limit,
        download_path=args.download,
        scroll_count=args.scroll,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
