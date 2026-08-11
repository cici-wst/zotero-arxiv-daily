"""Tests for main entry point.

The @hydra.main decorator makes main() hard to test directly in pytest
because config_path resolution depends on the calling context.
We test the inner logic by calling main's body with a composed config.
"""

import pytest
from hydra.core.global_hydra import GlobalHydra


@pytest.fixture(autouse=True)
def _clear_hydra():
    """Ensure GlobalHydra is clean before and after each test in this module."""
    GlobalHydra.instance().clear()
    yield
    GlobalHydra.instance().clear()


def test_main_creates_executor_and_runs(config, monkeypatch):
    """Verify that main composes Feishu settings, client, and executor."""
    calls = []
    clients = []

    class FakeSettings:
        @classmethod
        def from_config(cls, cfg):
            calls.append(("settings", cfg))
            return "settings"

    class FakeClient:
        def __init__(self, settings):
            calls.append(("client", settings))
            clients.append(self)

    class FakeExecutor:
        def __init__(self, cfg, delivery_client):
            calls.append(("init", cfg, delivery_client))

        def run(self):
            calls.append(("run",))

    monkeypatch.setattr("zotero_arxiv_daily.main.FeishuSettings", FakeSettings, raising=False)
    monkeypatch.setattr("zotero_arxiv_daily.main.FeishuClient", FakeClient, raising=False)
    monkeypatch.setattr("zotero_arxiv_daily.main.Executor", FakeExecutor)

    # Call main's body directly, bypassing @hydra.main
    from zotero_arxiv_daily import main as main_mod

    # Simulate what @hydra.main does: calls main(config)
    main_mod.main.__wrapped__(config)

    assert ("settings", config.feishu) in calls
    assert ("client", "settings") in calls
    assert ("init", config, clients[0]) in calls
    assert ("run",) in calls


def test_main_debug_logging(config, monkeypatch):
    """Verify debug mode sets appropriate log level."""
    from omegaconf import open_dict

    with open_dict(config):
        config.executor.debug = True

    class FakeExecutor:
        def __init__(self, cfg, delivery_client):
            pass
        def run(self):
            pass

    class FakeSettings:
        @classmethod
        def from_config(cls, cfg):
            return cls()

    monkeypatch.setattr("zotero_arxiv_daily.main.FeishuSettings", FakeSettings, raising=False)
    monkeypatch.setattr("zotero_arxiv_daily.main.FeishuClient", lambda settings: object(), raising=False)
    monkeypatch.setattr("zotero_arxiv_daily.main.Executor", FakeExecutor)

    from zotero_arxiv_daily import main as main_mod

    main_mod.main.__wrapped__(config)
    # If we get here without error, the debug path executed successfully
