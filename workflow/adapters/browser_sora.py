"""Sora browser adapter — automates the sora.chatgpt.com web UI via agent-browser + CDP.

Uses the Sora web UI instead of the API for higher quality output.
Connects to Chrome via CDP (Chrome DevTools Protocol) using agent-browser CLI.

Setup (one-time):
    1. Quit Chrome
    2. Create a symlinked profile:
        mkdir -p /tmp/chrome-cdp
        ln -sfn "$HOME/Library/Application Support/Google/Chrome/Default" /tmp/chrome-cdp/Default
        ln -sfn "$HOME/Library/Application Support/Google/Chrome/Local State" /tmp/chrome-cdp/
    3. Launch Chrome with CDP:
        /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
            --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-cdp
    4. Log into sora.chatgpt.com in the browser (one-time, session persists)

Flow: navigate → paste prompt → submit → poll drafts → match by prompt → download.

Limitations:
    - Duration: 10s or 15s only (web UI constraint).
    - Text-to-video only (no start frame / image-to-video).
    - Requires agent-browser CLI installed (`npm i -g @anthropic/agent-browser` or brew).
    - Chrome must be running with CDP on port 9222.

Cost: $0 direct (uses ChatGPT Plus/Pro subscription credits).
"""

import json
import os
import re
import subprocess
import sys
import time

from workflow.adapters.base import Adapter, Status
from workflow.adapters.registry import register

SORA_EXPLORE_URL = "https://sora.chatgpt.com/explore"
SORA_DRAFTS_URL = "https://sora.chatgpt.com/drafts"
CDP_PORT = "9222"


def _run(cmd: str, timeout: int = 30) -> tuple[int, str]:
    """Run an agent-browser command via CDP. Returns (exit_code, output)."""
    full_cmd = f"agent-browser --cdp {CDP_PORT} {cmd}"
    try:
        result = subprocess.run(
            full_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        return result.returncode, output.strip()
    except subprocess.TimeoutExpired:
        return 1, "Command timed out"


def _snapshot(timeout: int = 15) -> str:
    """Get accessibility tree of current page."""
    _, output = _run("snapshot -i", timeout=timeout)
    return output


def _screenshot(path: str) -> bool:
    """Take a screenshot and save it."""
    code, _ = _run(f"screenshot {path}", timeout=15)
    return code == 0


@register("browser_sora")
class BrowserSoraAdapter(Adapter):
    """Automates the Sora web UI for video generation via agent-browser + CDP.

    Config keys:
        prompt (str): Video generation prompt (required).
        output_dir (str): Directory for output video (required).
        output_filename (str): Output filename (default "video_sora_browser.mp4").
    """

    _jobs: dict[str, dict] = {}

    def health_check(self) -> bool:
        """Check that Chrome is reachable on CDP port and agent-browser is installed."""
        import shutil
        if not shutil.which("agent-browser"):
            return False
        code, output = _run("snapshot -i", timeout=15)
        return code == 0

    @property
    def timeout_seconds(self) -> int:
        return 900

    @property
    def input_types(self) -> dict[str, str]:
        return {}

    @property
    def output_type(self) -> str:
        return "video"

    def submit(self, config: dict) -> str:
        self._preflight()

        prompt = config.get("prompt", "")
        if not prompt:
            raise ValueError("'prompt' is required for browser_sora")

        output_dir = config.get("output_dir", ".")
        os.makedirs(output_dir, exist_ok=True)

        # Navigate to Sora explore page
        # Use eval to navigate — avoids agent-browser's strict load timeout
        _run(f'eval "window.location.href=\'{SORA_EXPLORE_URL}\'"', timeout=15)
        _run("wait 5000", timeout=10)

        # Fill the prompt — find the textarea and type
        # The prompt box placeholder is "Describe your video..."
        escaped_prompt = prompt.replace('"', '\\"').replace("'", "\\'")
        code, output = _run(f'fill "textarea" "{escaped_prompt}"', timeout=15)
        if code != 0:
            # Fallback: try clicking and typing
            _run('click "textarea"', timeout=10)
            _run("wait 500", timeout=5)
            _run(f'keyboard type "{escaped_prompt}"', timeout=30)

        _run("wait 1000", timeout=5)

        # Press Enter or click submit button to send
        # Try pressing Enter first (works in some UIs)
        _run("press Enter", timeout=10)
        _run("wait 3000", timeout=10)

        # Generate job ID
        job_id = f"browser_sora_{int(time.time())}"

        self._jobs[job_id] = {
            "prompt": prompt,
            "prompt_snippet": prompt[:80],
            "output_dir": output_dir,
            "output_filename": config.get("output_filename", "video_sora_browser.mp4"),
            "start_time": time.time(),
            "downloaded": False,
        }

        self.log_prompt(config, {"prompt": prompt, "source": "sora_web_ui"}, model="sora-web")

        print(f"  [browser_sora] Submitted prompt, job_id={job_id}", file=sys.stderr)
        return job_id

    def poll(self, job_id: str) -> tuple[Status, dict]:
        job_info = self._jobs.get(job_id)
        if not job_info:
            return Status.FAILED, {"error": f"Unknown job: {job_id}"}

        elapsed = time.time() - job_info["start_time"]
        metadata: dict = {"elapsed_seconds": round(elapsed, 1)}

        # Already downloaded
        if job_info.get("downloaded"):
            output_path = os.path.join(job_info["output_dir"], job_info["output_filename"])
            if os.path.exists(output_path):
                metadata["progress"] = 1.0
                metadata["output"] = output_path
                return Status.COMPLETED, metadata

        snippet = job_info["prompt_snippet"]

        # Navigate to drafts page
        code, _ = _run(f'open "{SORA_DRAFTS_URL}"', timeout=30)
        if code != 0:
            metadata["error"] = "Failed to navigate to drafts page"
            return Status.RUNNING, metadata

        _run("wait 3000", timeout=10)

        # Get page snapshot to find draft links
        snapshot = _snapshot(timeout=20)

        # Find draft links (href containing /d/gen_)
        gen_links = re.findall(r'href="(/d/gen_[^"]+)"', snapshot)
        if not gen_links:
            # Also try finding refs that look like draft cards
            metadata["progress"] = 0.1
            return Status.PENDING, metadata

        # Click through each draft to find ours
        for gen_link in gen_links:
            full_url = f"https://sora.chatgpt.com{gen_link}"
            _run(f'open "{full_url}"', timeout=30)
            _run("wait 2000", timeout=10)

            # Get page text to match prompt
            code, page_text = _run("eval 'document.body.innerText'", timeout=15)

            if snippet in page_text:
                # Found our draft
                if "Something went wrong" in page_text:
                    metadata["error"] = "Generation failed in Sora web UI"
                    return Status.FAILED, metadata

                # Try to download
                output_path = self._download(job_info)
                if output_path:
                    job_info["downloaded"] = True
                    metadata["progress"] = 1.0
                    metadata["output"] = output_path
                    return Status.COMPLETED, metadata

                # Draft exists but not downloadable yet
                metadata["progress"] = 0.5
                return Status.RUNNING, metadata

        # No matching draft found
        metadata["progress"] = 0.1
        return Status.PENDING, metadata

    def _download(self, job_info: dict) -> str | None:
        """Download video from the current draft detail page."""
        output_dir = job_info["output_dir"]
        filename = job_info["output_filename"]
        output_path = os.path.join(output_dir, filename)

        try:
            # Click three-dot menu
            code, _ = _run('click "text=…"', timeout=10)
            if code != 0:
                _run('click "[aria-label*=More]"', timeout=10)
            _run("wait 1000", timeout=5)

            # Click Download
            code, _ = _run(f'download "text=Download" "{output_path}"', timeout=120)
            if code != 0:
                print(f"  [browser_sora] Download command failed", file=sys.stderr)
                return None

            if os.path.exists(output_path):
                print(f"  [browser_sora] Downloaded → {output_path}", file=sys.stderr)
                return output_path

            return None

        except Exception as exc:
            print(f"  [browser_sora] Download failed: {exc}", file=sys.stderr)
            return None

    def get_result(self, job_id: str) -> str:
        job_info = self._jobs.get(job_id, {})
        output_dir = job_info.get("output_dir", ".")
        filename = job_info.get("output_filename", "video_sora_browser.mp4")
        output_path = os.path.join(output_dir, filename)
        if not os.path.exists(output_path):
            raise FileNotFoundError(f"Result not found: {output_path}")
        return output_path
