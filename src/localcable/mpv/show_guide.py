"""POST remote actions from mpv. Default (no action) raises the guide.

This helper only POSTs; it does not change the player window.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        return 2
    base = str(args[0]).rstrip("/")
    action = str(args[1]).strip().lower() if len(args) > 1 else "guide"
    if action in {"guide", "back", "exit"}:
        request = urllib.request.Request(base + "/api/show-guide", method="POST")
    else:
        body: dict[str, object] = {"action": action}
        if action == "digit" and len(args) > 2:
            body["digit"] = str(args[2])
        if action == "tune" and len(args) > 2:
            try:
                body["channel"] = int(args[2])
            except ValueError:
                return 2
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            base + "/api/remote",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
    try:
        urllib.request.urlopen(request, timeout=3)
    except (urllib.error.URLError, TimeoutError, OSError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
