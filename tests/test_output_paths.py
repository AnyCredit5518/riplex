import errno
from pathlib import Path

from riplex.output_paths import (
    preflight_configured_output_root,
    preflight_configured_rip_outputs,
    preflight_output_directory,
    preflight_rip_outputs,
    resolve_output_path,
)


def test_resolve_output_path_expands_user_home():
    assert resolve_output_path("~/Videos") == (Path.home() / "Videos").absolute()


def test_dry_run_resolves_without_creating_directory(tmp_path):
    target = tmp_path / "missing" / "Rips"

    result = preflight_output_directory(target, create=False)

    assert result.ok
    assert result.path == target.absolute()
    assert not target.exists()


def test_dry_run_rejects_existing_file(tmp_path):
    target = tmp_path / "Rips"
    target.write_text("not a directory", encoding="utf-8")

    result = preflight_output_directory(target, create=False)

    assert not result.ok
    assert result.error is not None
    assert str(target) in result.error
    assert "Not a directory" in result.error


def test_dry_run_rejects_unreadable_directory(tmp_path, monkeypatch):
    target = tmp_path / "Rips"
    target.mkdir()
    original_scandir = __import__("os").scandir

    def deny_scandir(path):
        if Path(path) == target:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_scandir(path)

    monkeypatch.setattr("riplex.output_paths.os.scandir", deny_scandir)

    result = preflight_output_directory(target, create=False)

    assert not result.ok
    assert result.error is not None
    assert "Permission denied" in result.error


def test_execute_rejects_write_only_directory(tmp_path, monkeypatch):
    target = tmp_path / "Rips"
    target.mkdir()
    original_scandir = __import__("os").scandir

    def deny_scandir(path):
        if Path(path) == target:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return original_scandir(path)

    monkeypatch.setattr("riplex.output_paths.os.scandir", deny_scandir)

    result = preflight_output_directory(target, create=True)

    assert not result.ok
    assert result.error is not None
    assert "Permission denied" in result.error


def test_execute_creates_and_write_probes_directory(tmp_path):
    target = tmp_path / "new" / "Rips"

    result = preflight_output_directory(target, create=True)

    assert result.ok
    assert result.path == target.absolute()
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_permission_error_names_configured_and_denied_paths(tmp_path, monkeypatch):
    target = tmp_path / "Riplex" / "Raw"
    denied = tmp_path / "Riplex"

    def deny_mkdir(self, *args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied", str(denied))

    monkeypatch.setattr(Path, "mkdir", deny_mkdir)

    result = preflight_output_directory(target, create=True)

    assert not result.ok
    assert str(target) in result.error
    assert str(denied) in result.error
    assert "Permission denied" in result.error


def test_rip_outputs_dry_run_resolves_both_without_creating(tmp_path):
    output_root = tmp_path / "Videos"
    rip_output = tmp_path / "Riplex" / "Raw"

    result = preflight_rip_outputs(output_root, rip_output, create=False)

    assert result.ok
    assert result.output_root == output_root.absolute()
    assert result.rip_output == rip_output.absolute()
    assert not output_root.exists()
    assert not rip_output.exists()


def test_rip_outputs_reports_unusable_rip_directory(tmp_path):
    output_root = tmp_path / "Videos"
    blocking_file = tmp_path / "Riplex"
    blocking_file.write_text("not a directory", encoding="utf-8")
    rip_output = blocking_file / "Raw"

    result = preflight_rip_outputs(output_root, rip_output, create=True)

    assert not result.ok
    assert result.errors
    assert str(rip_output) in result.errors[0]


def test_probe_cleanup_error_is_reported_not_raised(tmp_path, monkeypatch):
    original_unlink = Path.unlink

    def deny_probe_unlink(self, *args, **kwargs):
        if self.name.startswith(".riplex-write-test-"):
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_probe_unlink)

    result = preflight_output_directory(tmp_path, create=True)

    assert not result.ok
    assert result.error is not None
    assert "Permission denied" in result.error


def test_configured_rip_outputs_apply_cli_override_to_both_roots(tmp_path):
    override = tmp_path / "override"

    result = preflight_configured_rip_outputs(
        str(override),
        create=False,
    )

    assert result.ok
    assert result.output_root == override.absolute()
    assert result.rip_output == override.absolute()


def test_configured_output_root_does_not_resolve_rip_output(
    tmp_path, monkeypatch,
):
    output_root = tmp_path / "Videos"
    monkeypatch.setattr(
        "riplex.config.get_output_root",
        lambda _override=None: str(output_root),
    )
    monkeypatch.setattr(
        "riplex.config.get_rip_output",
        lambda _override=None: (_ for _ in ()).throw(
            AssertionError("rip_output should not be resolved")
        ),
    )

    result = preflight_configured_output_root(create=True)

    assert result.ok
    assert result.path == output_root
    assert output_root.is_dir()


def test_configured_output_expansion_error_is_reported(monkeypatch):
    def fail_output_root(_override=None):
        raise RuntimeError("Could not determine home directory")

    monkeypatch.setattr("riplex.config.get_output_root", fail_output_root)

    result = preflight_configured_rip_outputs(create=False)

    assert not result.ok
    assert result.output_root is None
    assert result.errors == (
        "Cannot resolve output_root: Could not determine home directory",
    )


def test_configured_rip_expansion_error_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "riplex.config.get_output_root",
        lambda _override=None: str(tmp_path / "Videos"),
    )

    def fail_rip_output(_override=None):
        raise RuntimeError("Could not determine home directory")

    monkeypatch.setattr("riplex.config.get_rip_output", fail_rip_output)

    result = preflight_configured_rip_outputs(create=False)

    assert not result.ok
    assert result.output_root == tmp_path / "Videos"
    assert result.rip_output is None
    assert result.errors == (
        "Cannot resolve rip_output: Could not determine home directory",
    )