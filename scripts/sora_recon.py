#!/usr/bin/env python3
"""
Sora web UI recon — maps the UI elements we need to automate.
Uses Chrome DevTools Protocol via a minimal websocket implementation.
"""

import base64
import hashlib
import http.client
import json
import os
import socket
import struct
import time
import urllib.request


CDP_HOST = "127.0.0.1"
CDP_PORT = 9222


def get_tabs():
    """Get list of open tabs from CDP."""
    data = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json").read()
    return json.loads(data)


def get_tab_ws_url(tab_index=0):
    """Get websocket URL for a tab."""
    tabs = get_tabs()
    return tabs[tab_index]["webSocketDebuggerUrl"]


class SimpleCDP:
    """Minimal CDP websocket client using Python stdlib only."""

    def __init__(self, ws_url):
        # Parse ws://host:port/path
        ws_url = ws_url.replace("ws://", "")
        host_port, self.path = ws_url.split("/", 1)
        self.path = "/" + self.path
        self.host, port = host_port.split(":")
        self.port = int(port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))
        self._handshake()
        self._msg_id = 0

    def _handshake(self):
        """WebSocket handshake."""
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        self.sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
        if b"101" not in response.split(b"\r\n")[0]:
            raise ConnectionError(f"WebSocket handshake failed: {response.decode()}")

    def send(self, data):
        """Send a websocket text frame."""
        payload = data.encode("utf-8")
        frame = bytearray()
        frame.append(0x81)  # FIN + text
        mask_key = os.urandom(4)
        length = len(payload)
        if length < 126:
            frame.append(0x80 | length)  # masked
        elif length < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack(">H", length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack(">Q", length))
        frame.extend(mask_key)
        masked = bytearray(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        frame.extend(masked)
        self.sock.sendall(frame)

    def recv(self, timeout=30):
        """Receive a websocket text frame."""
        self.sock.settimeout(timeout)
        data = self._recv_bytes(2)
        opcode = data[0] & 0x0F
        masked = bool(data[1] & 0x80)
        length = data[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_bytes(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_bytes(8))[0]
        if masked:
            mask = self._recv_bytes(4)
        payload = self._recv_bytes(length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return payload.decode("utf-8")

    def _recv_bytes(self, n):
        """Receive exactly n bytes."""
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def command(self, method, params=None, timeout=30):
        """Send a CDP command and wait for the response."""
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params
        self.send(json.dumps(msg))
        while True:
            raw = self.recv(timeout)
            result = json.loads(raw)
            if result.get("id") == self._msg_id:
                return result
            # Skip events, keep reading

    def close(self):
        """Close the connection."""
        try:
            self.sock.close()
        except Exception:
            pass


def screenshot(cdp, path):
    """Take a screenshot and save it."""
    result = cdp.command("Page.captureScreenshot", {"format": "png"}, timeout=10)
    if "result" in result and "data" in result["result"]:
        with open(path, "wb") as f:
            f.write(base64.b64decode(result["result"]["data"]))
        print(f"Screenshot saved to {path}")
        return True
    print(f"Screenshot failed: {result}")
    return False


def get_url(cdp):
    """Get current page URL."""
    result = cdp.command("Runtime.evaluate", {"expression": "window.location.href"})
    return result.get("result", {}).get("result", {}).get("value", "unknown")


def eval_js(cdp, expression, timeout=10):
    """Evaluate JavaScript and return the result."""
    result = cdp.command("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
    }, timeout=timeout)
    return result.get("result", {}).get("result", {}).get("value")


def main():
    print("=== Sora Web UI Recon ===\n")

    # Connect to first tab
    ws_url = get_tab_ws_url(0)
    print(f"Connecting to: {ws_url}")
    cdp = SimpleCDP(ws_url)
    cdp.command("Page.enable")

    # Navigate to sora.com
    print("Navigating to sora.com...")
    cdp.command("Page.navigate", {"url": "https://sora.com"})

    # Wait for load — page will redirect through Cloudflare
    print("Waiting for page load (15s)...")
    time.sleep(15)

    # Reconnect (navigation may have changed the page context)
    cdp.close()
    ws_url = get_tab_ws_url(0)
    cdp = SimpleCDP(ws_url)

    url = get_url(cdp)
    print(f"Current URL: {url}")

    # Screenshot
    screenshot(cdp, "/tmp/sora-recon-1.png")

    if "login" in url.lower() or "auth" in url.lower():
        print("\n⚠️  Not logged in. You'll need to log in manually in the debug Chrome.")
        print("   After logging in, run this script again.")
        cdp.close()
        return

    # Map the UI elements
    print("\n--- Mapping UI Elements ---\n")

    # Look for prompt input
    prompt_info = eval_js(cdp, """
    (() => {
        const textareas = document.querySelectorAll('textarea');
        const inputs = document.querySelectorAll('input[type="text"]');
        const contentEditables = document.querySelectorAll('[contenteditable="true"]');
        return JSON.stringify({
            textareas: Array.from(textareas).map(el => ({
                id: el.id,
                name: el.name,
                placeholder: el.placeholder,
                className: el.className.substring(0, 100),
                ariaLabel: el.getAttribute('aria-label')
            })),
            textInputs: Array.from(inputs).map(el => ({
                id: el.id,
                name: el.name,
                placeholder: el.placeholder,
                className: el.className.substring(0, 100)
            })),
            contentEditables: Array.from(contentEditables).map(el => ({
                tag: el.tagName,
                id: el.id,
                className: el.className.substring(0, 100),
                role: el.getAttribute('role')
            }))
        });
    })()
    """)
    print(f"Prompt inputs: {prompt_info}")

    # Look for file upload inputs
    upload_info = eval_js(cdp, """
    (() => {
        const fileInputs = document.querySelectorAll('input[type="file"]');
        const dropZones = document.querySelectorAll('[class*="drop"], [class*="upload"], [data-testid*="upload"]');
        return JSON.stringify({
            fileInputs: Array.from(fileInputs).map(el => ({
                id: el.id,
                name: el.name,
                accept: el.accept,
                multiple: el.multiple
            })),
            dropZones: Array.from(dropZones).map(el => ({
                tag: el.tagName,
                id: el.id,
                className: el.className.substring(0, 100)
            }))
        });
    })()
    """)
    print(f"Upload elements: {upload_info}")

    # Look for generate/create buttons
    button_info = eval_js(cdp, """
    (() => {
        const buttons = document.querySelectorAll('button');
        return JSON.stringify(
            Array.from(buttons).map(el => ({
                text: el.textContent.trim().substring(0, 50),
                id: el.id,
                className: el.className.substring(0, 80),
                ariaLabel: el.getAttribute('aria-label'),
                disabled: el.disabled,
                type: el.type
            })).filter(b => b.text || b.ariaLabel)
        );
    })()
    """)
    print(f"Buttons: {button_info}")

    # Look for duration/aspect ratio controls
    controls_info = eval_js(cdp, """
    (() => {
        const selects = document.querySelectorAll('select');
        const radioGroups = document.querySelectorAll('[role="radiogroup"], [role="tablist"]');
        const sliders = document.querySelectorAll('input[type="range"]');
        return JSON.stringify({
            selects: Array.from(selects).map(el => ({
                id: el.id,
                name: el.name,
                options: Array.from(el.options).map(o => o.textContent.trim())
            })),
            radioGroups: Array.from(radioGroups).map(el => ({
                id: el.id,
                className: el.className.substring(0, 80),
                children: Array.from(el.children).map(c => c.textContent.trim().substring(0, 30))
            })),
            sliders: Array.from(sliders).map(el => ({
                id: el.id,
                min: el.min,
                max: el.max,
                value: el.value
            }))
        });
    })()
    """)
    print(f"Controls: {controls_info}")

    # Get page title and main content structure
    structure = eval_js(cdp, """
    (() => {
        const title = document.title;
        const main = document.querySelector('main') || document.querySelector('[role="main"]');
        const navItems = document.querySelectorAll('nav a, nav button');
        return JSON.stringify({
            title: title,
            hasMain: !!main,
            navItems: Array.from(navItems).map(el => el.textContent.trim().substring(0, 30)).filter(Boolean)
        });
    })()
    """)
    print(f"Page structure: {structure}")

    # Full page HTML summary (just key landmarks)
    landmarks = eval_js(cdp, """
    (() => {
        const body = document.body;
        if (!body) return 'no body';
        // Get all data-testid attributes
        const testIds = document.querySelectorAll('[data-testid]');
        return JSON.stringify({
            bodyClasses: body.className.substring(0, 200),
            testIds: Array.from(testIds).map(el => ({
                testId: el.getAttribute('data-testid'),
                tag: el.tagName,
                text: el.textContent.trim().substring(0, 30)
            })).slice(0, 30)
        });
    })()
    """)
    print(f"Landmarks: {landmarks}")

    print("\n--- Recon Complete ---")
    cdp.close()


if __name__ == "__main__":
    main()
