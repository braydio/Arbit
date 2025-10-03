"""GitHub repository watcher for automated pulls.

This module provides a small utility that polls the GitHub API for the latest
commit on a repository branch and performs a ``git pull`` when a new commit is
published. It is designed for long-running environments where keeping the local
checkout in sync with the remote (``braydio/pyNance`` by default) is desirable.

Usage example::

    python scripts/github_watcher.py --interval 120

The watcher respects the ``GITHUB_TOKEN`` environment variable (configurable via
``--token-env``) to authenticate with GitHub and avoid anonymous rate limits.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Optional
from urllib import error, request

LOGGER = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 60.0
DEFAULT_REPO = "braydio/Arbit"
DEFAULT_BRANCH = "main"
# Environment variable name expected to hold a GitHub token. The token value is
# resolved at runtime so sensitive data is not baked into the module.
DEFAULT_TOKEN_ENV = "GITHUB_TOKEN"
DEFAULT_TIMEOUT = 10.0


class GitHubWatcherError(RuntimeError):
    """Base error raised by :class:`GitHubWatcher`."""


@dataclass
class GitHubWatcher:
    """Polls a GitHub repository for new commits and pulls updates.

    Attributes:
        repo: The ``owner/name`` string of the repository to monitor.
        branch: Branch name to check for new commits.
        interval: Number of seconds to sleep between polling attempts.
        workdir: Path to the git repository that should receive ``git pull``.
        token: Optional GitHub token for authenticated API calls.
        timeout: Socket timeout in seconds for GitHub API requests.
    """

    repo: str
    branch: str = DEFAULT_BRANCH
    interval: float = DEFAULT_INTERVAL_SECONDS
    workdir: Optional[Path] = None
    token: Optional[str] = None
    timeout: float = DEFAULT_TIMEOUT
    _last_seen: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate configuration and normalise paths."""
        if "/" not in self.repo:
            msg = "Repository must be in 'owner/name' format."
            raise GitHubWatcherError(msg)

        if self.interval <= 0:
            msg = "Polling interval must be a positive number of seconds."
            raise GitHubWatcherError(msg)

        if self.timeout <= 0:
            msg = "Timeout must be a positive number of seconds."
            raise GitHubWatcherError(msg)

        if self.workdir is None:
            # Default to project root (one directory above scripts/).
            self.workdir = Path(__file__).resolve().parents[1]
        else:
            self.workdir = self.workdir.resolve()

        if not (self.workdir / ".git").exists():
            msg = f"The path '{self.workdir}' does not appear to be a git repository."
            raise GitHubWatcherError(msg)

        LOGGER.debug(
            "Initialised GitHubWatcher repo=%s branch=%s workdir=%s",
            self.repo,
            self.branch,
            self.workdir,
        )

    def fetch_latest_sha(self) -> str:
        """Return the latest commit SHA for the configured repository.

        Returns:
            The commit SHA string.

        Raises:
            GitHubWatcherError: If the request fails or returns an unexpected payload.
        """
        api_url = f"https://api.github.com/repos/{self.repo}/commits/{self.branch}"
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request_obj = request.Request(api_url, headers=headers)
        try:
            with request.urlopen(request_obj, timeout=self.timeout) as response:  # noqa: S310
                status = getattr(response, "status", None)
                if status is not None and status != HTTPStatus.OK:
                    msg = f"GitHub API responded with status {status}."
                    raise GitHubWatcherError(msg)
                payload = json.load(response)
        except (
            error.HTTPError
        ) as exc:  # pragma: no cover - exercised via URLError branch
            msg = f"GitHub API request failed with status {exc.code}."
            raise GitHubWatcherError(msg) from exc
        except error.URLError as exc:
            msg = "Failed to reach GitHub API."
            raise GitHubWatcherError(msg) from exc
        except json.JSONDecodeError as exc:
            msg = "Received malformed JSON from GitHub API."
            raise GitHubWatcherError(msg) from exc

        sha = payload.get("sha") if isinstance(payload, dict) else None
        if not isinstance(sha, str):
            msg = "GitHub API response did not contain a commit SHA."
            raise GitHubWatcherError(msg)

        LOGGER.debug("Latest commit on %s@%s is %s", self.repo, self.branch, sha)
        return sha

    def git_pull(self) -> None:
        """Execute ``git pull`` within the configured working directory."""
        cmd = ["git", "-C", str(self.workdir), "pull", "--ff-only"]
        LOGGER.info("Running '%s'", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)  # noqa: S603
        except (
            subprocess.CalledProcessError
        ) as exc:  # pragma: no cover - relies on git failure
            msg = "git pull failed"
            raise GitHubWatcherError(msg) from exc

    def run_once(self) -> bool:
        """Check for a new commit and pull if required.

        Returns:
            ``True`` if ``git pull`` was executed, ``False`` otherwise.
        """
        latest_sha = self.fetch_latest_sha()
        if self._last_seen is None:
            self._last_seen = latest_sha
            LOGGER.info("Initial commit recorded: %s", latest_sha)
            return False

        if latest_sha == self._last_seen:
            LOGGER.debug("No new commits detected (still at %s)", latest_sha)
            return False

        LOGGER.info("New commit detected: %s -> %s", self._last_seen, latest_sha)
        self.git_pull()
        self._last_seen = latest_sha
        return True

    def run(self) -> None:
        """Continuously monitor GitHub for changes."""
        LOGGER.info(
            "Watching %s on branch %s every %.1fs (workdir=%s)",
            self.repo,
            self.branch,
            self.interval,
            self.workdir,
        )
        while True:
            try:
                self.run_once()
            except GitHubWatcherError as exc:
                LOGGER.error("Watcher error: %s", exc)
            except Exception as exc:  # pragma: no cover - defensive guard
                LOGGER.exception("Unexpected watcher failure: %s", exc)
            time.sleep(self.interval)


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command line arguments for the watcher CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", default=DEFAULT_REPO, help="GitHub repository in owner/name format"
    )
    parser.add_argument(
        "--branch", default=DEFAULT_BRANCH, help="Repository branch to monitor"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Polling interval in seconds",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help="Path to the git repository to refresh (defaults to project root)",
    )
    parser.add_argument(
        "--token-env",
        default=DEFAULT_TOKEN_ENV,
        help="Environment variable that stores a GitHub token",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Timeout in seconds for GitHub API requests",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Poll once instead of running continuously",
    )
    parser.add_argument(
        "-d",
        "--daemon",
        action="store_true",
        help="Run in the background (POSIX only).",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional log file path (recommended when using --daemon)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ...)",
    )
    return parser.parse_args(argv)


def _daemonize(log_file: Optional[Path]) -> None:
    """Detach the current process and continue execution in the background.

    Args:
        log_file: Optional path that should receive redirected stdout and stderr.

    Raises:
        GitHubWatcherError: If daemonisation is unsupported or fails.
    """

    if os.name != "posix":  # pragma: no cover - platform dependent
        msg = "Daemon mode is only supported on POSIX systems."
        raise GitHubWatcherError(msg)

    try:
        pid = os.fork()
    except OSError as exc:  # pragma: no cover - fork failure is unlikely
        msg = "Failed to fork the daemon process (stage 1)."
        raise GitHubWatcherError(msg) from exc
    if pid > 0:
        raise SystemExit(0)

    os.setsid()

    try:
        pid = os.fork()
    except OSError as exc:  # pragma: no cover - fork failure is unlikely
        msg = "Failed to fork the daemon process (stage 2)."
        raise GitHubWatcherError(msg) from exc
    if pid > 0:
        os._exit(0)

    os.chdir("/")
    os.umask(0)

    sys.stdout.flush()
    sys.stderr.flush()

    with open(os.devnull, "rb", 0) as read_null:
        os.dup2(read_null.fileno(), 0)

    if log_file is not None:
        log_path = log_file.expanduser().resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab", 0) as log_handle:
            os.dup2(log_handle.fileno(), 1)
            os.dup2(log_handle.fileno(), 2)
    else:
        with open(os.devnull, "ab", 0) as write_null:
            os.dup2(write_null.fileno(), 1)
            os.dup2(write_null.fileno(), 2)


def main(argv: Optional[list[str]] = None) -> int:
    """Entry point for the GitHub watcher CLI."""
    args = _parse_args(argv)
    log_file = args.log_file.expanduser().resolve() if args.log_file else None
    handlers = None
    if log_file is not None:
        handlers = [logging.FileHandler(str(log_file))]

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )

    token = os.getenv(args.token_env) if args.token_env else None

    try:
        watcher = GitHubWatcher(
            repo=args.repo,
            branch=args.branch,
            interval=args.interval,
            workdir=args.workdir,
            token=token,
            timeout=args.timeout,
        )
    except GitHubWatcherError as exc:
        LOGGER.error("Invalid watcher configuration: %s", exc)
        return 1

    if args.daemon:
        try:
            _daemonize(log_file)
        except GitHubWatcherError as exc:
            LOGGER.error("Failed to start daemon: %s", exc)
            return 1

    try:
        if args.run_once:
            watcher.run_once()
        else:
            watcher.run()
    except KeyboardInterrupt:  # pragma: no cover - requires manual interrupt
        LOGGER.info("Watcher interrupted by user. Exiting.")
        return 0
    except GitHubWatcherError as exc:
        LOGGER.error("Watcher stopped due to error: %s", exc)
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via CLI execution
    raise SystemExit(main())
