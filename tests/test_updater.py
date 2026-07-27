import subprocess
import updater


class FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _mock_run_factory(responses):
    """responses: dict mapping a recognizable substring of the git/pip
    subcommand to a FakeCompletedProcess. Falls back to success/empty."""
    def _mock_run(args, cwd=None, capture_output=True, text=True, timeout=None):
        joined = " ".join(args)
        for key, response in responses.items():
            if key in joined:
                return response
        return FakeCompletedProcess(returncode=0, stdout="", stderr="")
    return _mock_run


def test_current_ref_not_a_git_repo(monkeypatch):
    monkeypatch.setattr(updater, "_is_git_repo", lambda: False)
    assert updater.current_ref() == "unknown (not a git checkout)"


def test_current_ref_on_a_tag(monkeypatch):
    monkeypatch.setattr(updater, "_is_git_repo", lambda: True)
    monkeypatch.setattr(subprocess, "run", _mock_run_factory({
        "describe --tags --exact-match": FakeCompletedProcess(returncode=0, stdout="v1.2.0\n"),
    }))
    assert updater.current_ref() == "v1.2.0"


def test_current_ref_falls_back_to_short_hash(monkeypatch):
    monkeypatch.setattr(updater, "_is_git_repo", lambda: True)
    monkeypatch.setattr(subprocess, "run", _mock_run_factory({
        "describe --tags --exact-match": FakeCompletedProcess(returncode=1, stdout=""),
        "rev-parse --short HEAD": FakeCompletedProcess(returncode=0, stdout="a1b2c3d\n"),
    }))
    assert updater.current_ref() == "a1b2c3d"


def test_check_for_update_not_a_git_repo(monkeypatch):
    monkeypatch.setattr(updater, "_is_git_repo", lambda: False)
    result = updater.check_for_update()
    assert result["update_available"] is False
    assert result["error"] is not None


def test_check_for_update_fetch_fails(monkeypatch):
    monkeypatch.setattr(updater, "_is_git_repo", lambda: True)
    monkeypatch.setattr(subprocess, "run", _mock_run_factory({
        "fetch --tags": FakeCompletedProcess(returncode=1, stderr="network error"),
    }))
    result = updater.check_for_update()
    assert result["update_available"] is False
    assert "couldn't reach" in result["error"].lower()


def test_check_for_update_available_via_tag(monkeypatch):
    monkeypatch.setattr(updater, "_is_git_repo", lambda: True)
    monkeypatch.setattr(subprocess, "run", _mock_run_factory({
        "fetch --tags": FakeCompletedProcess(returncode=0),
        "tag --list": FakeCompletedProcess(returncode=0, stdout="v1.1.0\nv1.0.0\n"),
        "rev-list -n 1 v1.1.0": FakeCompletedProcess(returncode=0, stdout="newcommit123\n"),
        "rev-parse HEAD": FakeCompletedProcess(returncode=0, stdout="oldcommit456\n"),
        "describe --tags --exact-match": FakeCompletedProcess(returncode=0, stdout="v1.0.0\n"),
    }))
    result = updater.check_for_update()
    assert result["update_available"] is True
    assert result["latest"] == "v1.1.0"
    assert result["current"] == "v1.0.0"


def test_check_for_update_already_current(monkeypatch):
    monkeypatch.setattr(updater, "_is_git_repo", lambda: True)
    monkeypatch.setattr(subprocess, "run", _mock_run_factory({
        "fetch --tags": FakeCompletedProcess(returncode=0),
        "tag --list": FakeCompletedProcess(returncode=0, stdout="v1.0.0\n"),
        "rev-list -n 1 v1.0.0": FakeCompletedProcess(returncode=0, stdout="samecommit\n"),
        "rev-parse HEAD": FakeCompletedProcess(returncode=0, stdout="samecommit\n"),
        "describe --tags --exact-match": FakeCompletedProcess(returncode=0, stdout="v1.0.0\n"),
    }))
    result = updater.check_for_update()
    assert result["update_available"] is False


def test_check_for_update_no_tags_falls_back_to_main(monkeypatch):
    monkeypatch.setattr(updater, "_is_git_repo", lambda: True)
    monkeypatch.setattr(subprocess, "run", _mock_run_factory({
        "fetch --tags": FakeCompletedProcess(returncode=0),
        "tag --list": FakeCompletedProcess(returncode=0, stdout=""),
        "rev-parse origin/main": FakeCompletedProcess(returncode=0, stdout="mainhead789\n"),
        "rev-parse HEAD": FakeCompletedProcess(returncode=0, stdout="oldcommit456\n"),
        "describe --tags --exact-match": FakeCompletedProcess(returncode=1, stdout=""),
        "rev-parse --short HEAD": FakeCompletedProcess(returncode=0, stdout="oldcomm\n"),
    }))
    result = updater.check_for_update()
    assert result["latest"] == "main"
    assert result["update_available"] is True


def test_apply_update_when_already_current(monkeypatch):
    monkeypatch.setattr(updater, "check_for_update", lambda: {
        "current": "v1.0.0", "latest": "v1.0.0", "update_available": False, "error": None,
    })
    result = updater.apply_update()
    assert result["ok"] is True
    assert result["updated"] is False


def test_apply_update_when_check_errors(monkeypatch):
    monkeypatch.setattr(updater, "check_for_update", lambda: {
        "current": "unknown", "latest": None, "update_available": False,
        "error": "Couldn't reach GitHub.",
    })
    result = updater.apply_update()
    assert result["ok"] is False
    assert "GitHub" in result["error"]


def test_apply_update_success_triggers_restart(monkeypatch):
    monkeypatch.setattr(updater, "check_for_update", lambda: {
        "current": "v1.0.0", "latest": "v1.1.0", "update_available": True, "error": None,
    })
    monkeypatch.setattr(subprocess, "run", _mock_run_factory({
        "checkout v1.1.0": FakeCompletedProcess(returncode=0),
        "install -r requirements.txt": FakeCompletedProcess(returncode=0),
    }))
    restart_calls = []
    monkeypatch.setattr(updater, "_restart_service_after_delay", lambda: restart_calls.append(1))
    result = updater.apply_update()
    assert result["ok"] is True
    assert result["updated"] is True
    assert len(restart_calls) == 1


def test_apply_update_checkout_fails(monkeypatch):
    monkeypatch.setattr(updater, "check_for_update", lambda: {
        "current": "v1.0.0", "latest": "v1.1.0", "update_available": True, "error": None,
    })
    monkeypatch.setattr(subprocess, "run", _mock_run_factory({
        "checkout v1.1.0": FakeCompletedProcess(returncode=1, stderr="conflict"),
    }))
    result = updater.apply_update()
    assert result["ok"] is False
    assert "checkout failed" in result["error"]


def test_apply_update_pip_install_fails(monkeypatch):
    monkeypatch.setattr(updater, "check_for_update", lambda: {
        "current": "v1.0.0", "latest": "v1.1.0", "update_available": True, "error": None,
    })
    monkeypatch.setattr(subprocess, "run", _mock_run_factory({
        "checkout v1.1.0": FakeCompletedProcess(returncode=0),
        "install -r requirements.txt": FakeCompletedProcess(returncode=1, stderr="broken package"),
    }))
    result = updater.apply_update()
    assert result["ok"] is False
    assert "dependency install failed" in result["error"]


def test_restart_service_after_delay_missing_sudo_does_not_crash(monkeypatch):
    def raise_not_found(*a, **k):
        raise FileNotFoundError("sudo not found")
    monkeypatch.setattr(subprocess, "Popen", raise_not_found)
    # Should not raise, even though the thread runs after a delay in real
    # use. Call the inner function directly to test synchronously.
    updater._restart_service_after_delay(delay_seconds=0)
    import time
    time.sleep(0.1)  # let the daemon thread run
