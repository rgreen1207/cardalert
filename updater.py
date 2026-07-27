"""
Self-update support for the "Check for updates" / "Update now" buttons on
the Settings page.

How it works:
1. Check: `git fetch` in the app's own directory, then compare the current
   commit against the latest tagged release (falling back to `origin/main`
   if no tags exist yet, same fallback `install.sh` uses).
2. Apply: `git checkout` the target ref, reinstall dependencies with the
   same interpreter/venv the app is already running under, then restart
   the systemd service so the new code actually takes effect.

Restarting itself is the one genuinely delicate part: the running process
has to trigger its own replacement. This uses `sudo -n systemctl restart
cardalert` in a detached subprocess, which only works non-interactively
because `install.sh` sets up a narrowly-scoped sudoers rule that permits
exactly that one command for exactly this service, nothing broader. If
that rule isn't present (e.g. a manual install that skipped it), the git
pull and dependency install still succeed; only the automatic restart
step will silently fail, and a manual `sudo systemctl restart cardalert`
finishes the job.

Every subprocess call here uses a fixed argument list (no shell=True, no
string interpolation of anything a user typed), so there's no command
injection surface even though this endpoint does execute real commands.
"""
import os
import sys
# subprocess is required here for the git/pip/systemctl calls below.
# Every call uses a fixed argument list, never shell=True, and nothing
# user-supplied ever reaches these commands.
import subprocess  # nosec B404
import threading
import time

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_NAME = "cardalert"
GIT_TIMEOUT = 30
PIP_TIMEOUT = 120


def _run(args, timeout=GIT_TIMEOUT, cwd=None):
    if cwd is None:
        cwd = REPO_DIR
    # Fixed arg list, no shell, no user input reaches this call.
    return subprocess.run(  # nosec B603
        args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
    )


def _is_git_repo() -> bool:
    return os.path.isdir(os.path.join(REPO_DIR, ".git"))


def current_ref() -> str:
    """Human-readable label for what's currently checked out: a tag name
    if HEAD is exactly on one, otherwise a short commit hash."""
    if not _is_git_repo():
        return "unknown (not a git checkout)"
    tag = _run(["git", "describe", "--tags", "--exact-match"])
    if tag.returncode == 0:
        return tag.stdout.strip()
    short = _run(["git", "rev-parse", "--short", "HEAD"])
    return short.stdout.strip() if short.returncode == 0 else "unknown"


def _latest_tag():
    tags = _run(["git", "tag", "--list", "--sort=-v:refname"])
    if tags.returncode != 0:
        return None
    lines = [t for t in tags.stdout.splitlines() if t.strip()]
    return lines[0] if lines else None


def check_for_update() -> dict:
    """Returns {"current": str, "latest": str, "update_available": bool,
    "error": str|None}. Never raises; network/git failures come back as
    a populated "error" field so the UI can show something reasonable."""
    if not _is_git_repo():
        return {"current": current_ref(), "latest": None,
                "update_available": False,
                "error": "Not a git checkout, can't check for updates this way."}

    fetch = _run(["git", "fetch", "--tags", "origin", "main"], timeout=GIT_TIMEOUT)
    if fetch.returncode != 0:
        return {"current": current_ref(), "latest": None,
                "update_available": False,
                "error": "Couldn't reach GitHub to check for updates."}

    latest_tag = _latest_tag()
    if latest_tag:
        target_ref = latest_tag
        target_commit = _run(["git", "rev-list", "-n", "1", latest_tag]).stdout.strip()
    else:
        target_ref = "main"
        target_commit = _run(["git", "rev-parse", "origin/main"]).stdout.strip()

    current_commit = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    update_available = bool(target_commit) and target_commit != current_commit

    return {
        "current": current_ref(),
        "latest": target_ref,
        "update_available": update_available,
        "error": None,
    }


def _pip_path() -> str:
    """Use the same interpreter/venv this process is already running
    under, whatever that happens to be, rather than assuming a path."""
    candidate = os.path.join(os.path.dirname(sys.executable), "pip")
    return candidate if os.path.exists(candidate) else "pip"


def _restart_service_after_delay(delay_seconds=1.5):
    def _do_restart():
        time.sleep(delay_seconds)  # let the HTTP response go out first
        sudo_path = "/usr/bin/sudo" if os.path.exists("/usr/bin/sudo") else "sudo"
        systemctl_path = "/bin/systemctl" if os.path.exists("/bin/systemctl") else \
            ("/usr/bin/systemctl" if os.path.exists("/usr/bin/systemctl") else "systemctl")
        try:
            # Fixed arg list, no shell, no user input; SERVICE_NAME is a
            # hardcoded constant, never derived from a request.
            subprocess.Popen(  # nosec B603
                [sudo_path, "-n", systemctl_path, "restart", SERVICE_NAME],
                start_new_session=True,
            )
        except (OSError, FileNotFoundError):
            pass  # no sudo rule set up, git pull still succeeded, manual restart needed

    threading.Thread(target=_do_restart, daemon=True).start()


def apply_update() -> dict:
    """Pulls the latest release, reinstalls dependencies, and schedules a
    service restart a couple seconds out. Returns before the restart
    actually happens, so the caller gets a real HTTP response first."""
    status = check_for_update()
    if status["error"]:
        return {"ok": False, "error": status["error"]}
    if not status["update_available"]:
        return {"ok": True, "updated": False, "message": "Already up to date."}

    target = status["latest"]
    checkout = _run(["git", "checkout", target])
    if checkout.returncode != 0:
        return {"ok": False, "error": f"git checkout failed: {checkout.stderr.strip()[:300]}"}

    pip = _pip_path()
    install = _run([pip, "install", "-r", "requirements.txt"], timeout=PIP_TIMEOUT)
    if install.returncode != 0:
        return {"ok": False, "error": f"dependency install failed: {install.stderr.strip()[:300]}"}

    _restart_service_after_delay()
    return {"ok": True, "updated": True, "message": f"Updated to {target}. Restarting now."}
