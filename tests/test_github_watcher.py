"""Tests for the GitHub watcher utility script."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import github_watcher  # noqa: E402


class DummyResponse(io.StringIO):
    """Simple HTTP response stub for GitHub API calls."""

    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        super().__init__(json.dumps(payload))
        self.status = status


@pytest.fixture()
def repo_dir(tmp_path: Path) -> Path:
    """Create a temporary git repository directory for tests."""

    path = tmp_path / "repo"
    path.mkdir()
    (path / ".git").mkdir()
    return path


def test_fetch_latest_sha_success(
    monkeypatch: pytest.MonkeyPatch, repo_dir: Path
) -> None:
    """GitHubWatcher should return the commit SHA from a valid API response."""

    watcher = github_watcher.GitHubWatcher(repo="owner/name", workdir=repo_dir)
    dummy_response = DummyResponse({"sha": "abc123"})
    monkeypatch.setattr(
        github_watcher.request,
        "urlopen",
        mock.Mock(return_value=dummy_response),
    )

    assert watcher.fetch_latest_sha() == "abc123"


def test_fetch_latest_sha_missing_sha(
    monkeypatch: pytest.MonkeyPatch, repo_dir: Path
) -> None:
    """GitHubWatcher should raise an error when the SHA is missing from the payload."""

    watcher = github_watcher.GitHubWatcher(repo="owner/name", workdir=repo_dir)
    monkeypatch.setattr(
        github_watcher.request,
        "urlopen",
        mock.Mock(return_value=DummyResponse({})),
    )

    with pytest.raises(github_watcher.GitHubWatcherError):
        watcher.fetch_latest_sha()


def test_run_once_triggers_pull(
    monkeypatch: pytest.MonkeyPatch, repo_dir: Path
) -> None:
    """GitHubWatcher.run_once should invoke git pull when the commit changes."""

    watcher = github_watcher.GitHubWatcher(repo="owner/name", workdir=repo_dir)
    fetch_mock = mock.Mock(side_effect=["sha1", "sha1", "sha2"])
    monkeypatch.setattr(watcher, "fetch_latest_sha", fetch_mock)
    run_mock = mock.Mock()
    monkeypatch.setattr(github_watcher.subprocess, "run", run_mock)

    assert watcher.run_once() is False
    assert watcher.run_once() is False
    assert watcher.run_once() is True

    run_mock.assert_called_once_with(
        ["git", "-C", str(repo_dir), "pull", "--ff-only"], check=True
    )


def test_daemonize_requires_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    """_daemonize should raise on non-POSIX platforms."""

    monkeypatch.setattr(github_watcher.os, "name", "nt", raising=False)

    with pytest.raises(github_watcher.GitHubWatcherError):
        github_watcher._daemonize(None)


def test_main_daemon_runs_once(monkeypatch: pytest.MonkeyPatch, repo_dir: Path) -> None:
    """main should daemonise and then execute run_once when requested."""

    daemon_mock = mock.Mock()
    monkeypatch.setattr(github_watcher, "_daemonize", daemon_mock)
    monkeypatch.setattr(github_watcher.logging, "basicConfig", mock.Mock())

    watcher = mock.Mock()
    watcher.run_once = mock.Mock()
    watcher.run = mock.Mock()
    monkeypatch.setattr(
        github_watcher, "GitHubWatcher", mock.Mock(return_value=watcher)
    )

    exit_code = github_watcher.main(
        [
            "--repo",
            "owner/name",
            "--workdir",
            str(repo_dir),
            "--daemon",
            "--run-once",
        ]
    )

    assert exit_code == 0
    daemon_mock.assert_called_once_with(None)
    watcher.run_once.assert_called_once()
    watcher.run.assert_not_called()


def test_main_daemon_failure(monkeypatch: pytest.MonkeyPatch, repo_dir: Path) -> None:
    """main should report daemonisation errors and exit with failure."""

    daemon_error = github_watcher.GitHubWatcherError("boom")
    monkeypatch.setattr(
        github_watcher,
        "_daemonize",
        mock.Mock(side_effect=daemon_error),
    )
    monkeypatch.setattr(github_watcher.logging, "basicConfig", mock.Mock())

    watcher = mock.Mock()
    watcher.run_once = mock.Mock()
    watcher.run = mock.Mock()
    monkeypatch.setattr(
        github_watcher, "GitHubWatcher", mock.Mock(return_value=watcher)
    )

    exit_code = github_watcher.main(
        [
            "--repo",
            "owner/name",
            "--workdir",
            str(repo_dir),
            "--daemon",
            "--run-once",
        ]
    )

    assert exit_code == 1
    watcher.run_once.assert_not_called()
