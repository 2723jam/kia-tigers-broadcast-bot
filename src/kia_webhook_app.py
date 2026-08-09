from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
import requests

try:
    from kia_broadcast_bot import (
        USER_AGENT,
        build_telegram_webhook_response,
        process_telegram_update,
        run_scheduled_check,
    )
except ModuleNotFoundError:
    from .kia_broadcast_bot import (
        USER_AGENT,
        build_telegram_webhook_response,
        process_telegram_update,
        run_scheduled_check,
    )


logger = logging.getLogger(__name__)
app = FastAPI(title="KIA Tigers Telegram Webhook")


@app.get("/")
@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/cron/kia-broadcast")
@app.post("/api/cron/kia-broadcast")
@app.get("/api/kia_cron")
@app.post("/api/kia_cron")
async def kia_broadcast_cron(request: Request) -> dict[str, Any]:
    _verify_cron_request(request)

    if _dispatch_github_broadcast_workflow():
        return {"ok": True, "mode": "github_workflow_dispatch"}

    result = run_scheduled_check()
    if result != 0:
        raise HTTPException(status_code=502, detail="Scheduled check failed")
    return {"ok": True, "mode": "direct_scheduled_check"}


@app.post("/")
@app.post("/api/telegram")
@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, Any]:
    expected_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if expected_secret and x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")

    update = await _read_update(request)
    response_payload = build_telegram_webhook_response(update)
    if response_payload:
        return response_payload

    if not process_telegram_update(update):
        logger.error("Telegram update handling failed: %s", update.get("update_id"))
        raise HTTPException(status_code=502, detail="Telegram update handling failed")

    return {"ok": True}


async def _read_update(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid Telegram update payload")
    return payload


def _verify_cron_request(request: Request) -> None:
    expected_secret = os.environ.get("CRON_SECRET", "").strip()
    if not expected_secret:
        return

    authorization = request.headers.get("authorization", "")
    if authorization != f"Bearer {expected_secret}":
        raise HTTPException(status_code=401, detail="Invalid cron secret")


def _dispatch_github_broadcast_workflow() -> bool:
    token = os.environ.get("GITHUB_DISPATCH_TOKEN", "").strip()
    if not token:
        return False

    repository = os.environ.get(
        "GITHUB_DISPATCH_REPOSITORY", "2723jam/kia-tigers-broadcast-bot"
    )
    workflow = os.environ.get("GITHUB_DISPATCH_WORKFLOW", "kia-broadcast.yml")
    ref = os.environ.get("GITHUB_DISPATCH_REF", "main")
    url = f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json={"ref": ref},
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.error("GitHub workflow dispatch failed: %s", exc)
        return False

    if response.status_code == 204:
        return True

    logger.error(
        "GitHub workflow dispatch returned %s: %s",
        response.status_code,
        response.text[:300],
    )
    return False
