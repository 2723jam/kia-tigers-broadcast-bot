from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


WORKFLOWS = (
    "kia-broadcast.yml",
    "kia-command.yml",
    "kia-workflow-guard.yml",
)


def main() -> int:
    repository = os.environ.get(
        "GITHUB_REPOSITORY", "2723jam/kia-tigers-broadcast-bot"
    )
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("GITHUB_TOKEN is missing.", file=sys.stderr)
        return 1

    failed = False
    for workflow in WORKFLOWS:
        if not enable_workflow(repository, workflow, token):
            failed = True

    return 1 if failed else 0


def enable_workflow(repository: str, workflow: str, token: str) -> bool:
    url = f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/enable"
    request = urllib.request.Request(
        url,
        method="PUT",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "kia-broadcast-bot/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status in (204, 200):
                print(f"enabled {workflow}")
                return True
            print(f"unexpected status for {workflow}: {response.status}", file=sys.stderr)
            return False
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(body).get("message", body)
        except json.JSONDecodeError:
            message = body
        print(f"failed to enable {workflow}: {exc.code} {message}", file=sys.stderr)
        return False
    except OSError as exc:
        print(f"failed to enable {workflow}: {exc}", file=sys.stderr)
        return False


if __name__ == "__main__":
    raise SystemExit(main())
