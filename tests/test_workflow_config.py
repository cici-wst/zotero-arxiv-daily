from pathlib import Path

import pytest


WORKFLOW_PATHS = (
    Path(".github/workflows/main.yml"),
    Path(".github/workflows/test.yml"),
)
FEISHU_SECRET_NAMES = (
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_WEBHOOK_URL",
)
EMAIL_SECRET_NAMES = (
    "SENDER",
    "SENDER_PASSWORD",
    "RECEIVER",
)


@pytest.mark.parametrize("workflow_path", WORKFLOW_PATHS)
def test_workflow_injects_feishu_secrets(workflow_path: Path):
    workflow = workflow_path.read_text(encoding="utf-8")

    for secret_name in FEISHU_SECRET_NAMES:
        assert f"{secret_name}: ${{{{ secrets.{secret_name} }}}}" in workflow


@pytest.mark.parametrize("workflow_path", WORKFLOW_PATHS)
def test_workflow_does_not_reference_email_secrets(workflow_path: Path):
    workflow = workflow_path.read_text(encoding="utf-8")

    for secret_name in EMAIL_SECRET_NAMES:
        assert f"secrets.{secret_name}" not in workflow
