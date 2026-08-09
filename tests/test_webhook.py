from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import kia_broadcast_bot as bot  # noqa: E402
import kia_webhook_app as webhook_app  # noqa: E402
from kia_webhook_app import app  # noqa: E402


def test_webhook_health():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_webhook_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    client = TestClient(app)

    response = client.post("/api/telegram", json={})

    assert response.status_code == 401


def test_webhook_processes_today_command(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "8124393248")
    monkeypatch.setattr(bot, "build_today_reply_text", lambda: "오늘 경기")
    monkeypatch.setattr(
        bot,
        "send_today_reply",
        lambda chat_id: (_ for _ in ()).throw(
            AssertionError("webhook should respond with sendMessage payload")
        ),
    )
    client = TestClient(app)

    response = client.post(
        "/api/telegram",
        headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        json={
            "update_id": 245966101,
            "message": {
                "text": "/today",
                "chat": {"id": 8124393248},
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "method": "sendMessage",
        "chat_id": "8124393248",
        "text": "오늘 경기",
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }


def test_cron_rejects_wrong_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    client = TestClient(app)

    response = client.get("/api/kia_cron")

    assert response.status_code == 401


def test_cron_dispatches_github_workflow_when_token_is_available(monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.setattr(webhook_app, "_dispatch_github_broadcast_workflow", lambda: True)
    monkeypatch.setattr(
        webhook_app,
        "run_scheduled_check",
        lambda: (_ for _ in ()).throw(
            AssertionError("cron should dispatch GitHub workflow first")
        ),
    )
    client = TestClient(app)

    response = client.get("/api/cron/kia-broadcast")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "mode": "github_workflow_dispatch"}


def test_cron_runs_direct_scheduled_check_without_dispatch_token(monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    monkeypatch.setattr(webhook_app, "_dispatch_github_broadcast_workflow", lambda: False)
    monkeypatch.setattr(webhook_app, "run_scheduled_check", lambda: 0)
    client = TestClient(app)

    response = client.post("/api/cron/kia-broadcast")

    assert response.status_code == 200
    assert response.json() == {"ok": True, "mode": "direct_scheduled_check"}
