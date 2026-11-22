"""Output-only check contracts, including native job creation with write sentinels."""
import json
import errno
import stat
import subprocess

from click.testing import CliRunner
import pytest

from takflow.artifact_checks import check_artifacts
from takflow.build import BuildError, build
from takflow.cli import create_cli
from test_build import application, data, put, resources


def snapshot(root):
    return {p.relative_to(root): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
            for p in root.rglob("*") if p.is_file()}


def test_checks_do_not_load_an_application_or_publish_a_manifest(tmp_path):
    cli = create_cli(lambda: pytest.fail("artifact checks initialized an application"))
    script = put(tmp_path, "job.sh", "#!/bin/sh\ntouch marker\n")
    result = CliRunner().invoke(cli, ["--format", "json", "check", "--shell", str(script)])
    assert result.exit_code == 0 and json.loads(result.output)["passed"]
    script.write_text("#!/bin/sh\nif then\n")
    result = CliRunner().invoke(cli, ["--format", "json", "check", "--shell", str(script)])
    assert result.exit_code == 1 and json.loads(result.output)["checks"][0]["status"] == "failed"
    assert not (tmp_path / "generation_manifest.json").exists()
    assert [p.name for p in tmp_path.iterdir()] == ["job.sh"]


def test_unavailable_engine_only_affects_selected_checks(tmp_path, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "ecflow", None)
    script = put(tmp_path, "job.sh", "#!/bin/sh\nexit 7\n")
    definition = put(tmp_path, "suite.def", "suite suite\nendsuite\n")
    assert check_artifacts(shell=[script]).passed
    result = check_artifacts(definition=definition, parse=True, shell=[script])
    assert [c["status"] for c in result.checks] == ["incomplete", "passed"]


def test_default_build_leaves_shell_and_definition_checks_to_the_caller(tmp_path, resources, monkeypatch):
    from jinja2 import Environment
    def unexpected(*args, **kwargs):
        pytest.fail("default build invoked additional checks")
    monkeypatch.setattr(Environment, "parse", unexpected)
    monkeypatch.setattr("takflow.checks.subprocess.run", unexpected)
    put(resources, "jobs/on/task.sh.j2", "#!/bin/bash\nif then\n")
    with application(resources).prepare(data(tmp_path / "out", mode="shell")) as context:
        result = build(context)
    assert result.complete and result.diagnostics == []
    assert [s.name for s in result.stages] == ["resource", "config", "credential", "job", "workflow", "report"]
    manifest = result.manifest_path.read_bytes()
    monkeypatch.undo()
    assert not check_artifacts(shell=[tmp_path / "out/jobs/on/task.sh"]).passed
    assert result.manifest_path.read_bytes() == manifest


def test_empty_inventory_cannot_pass_an_integrity_check(tmp_path):
    manifest = put(tmp_path, "generation_manifest.json", '{"artifacts": []}')
    result = check_artifacts(manifest=manifest, integrity=True)
    assert result.checks[0]["status"] == "failed"
    assert manifest.read_text() == '{"artifacts": []}'
    manifest.write_text(json.dumps({"output_root": str(tmp_path), "artifacts": [
        {"kind": "reference", "path": "/target-only/site"}]}))
    check, = check_artifacts(manifest=manifest, integrity=True).checks
    assert check["status"] == "incomplete" and "no local outputs" in check["reason"]


@pytest.mark.parametrize("format", ["text", "json"])
def test_check_distinguishes_syntax_from_tool_failure_without_writing(tmp_path, resources, monkeypatch, format):
    out = tmp_path / "out"
    private = "private-shell-line"
    # Default build can publish even when a generated script has bad syntax.
    put(resources, "jobs/on/task.sh.j2", f"#!/bin/bash\nif then {private}\n")
    with application(resources).prepare(data(out, mode="shell")) as ctx:
        built = build(ctx)
    assert built.complete
    target = out / "jobs/on/task.sh"
    before = snapshot(out)
    cli = create_cli(lambda: pytest.fail("check loaded an application"))
    args = ["--format", format, "check", "--shell", str(target), "--manifest", str(built.manifest_path), "--integrity"]
    def check(status, reason):
        response = CliRunner().invoke(cli, args)
        assert response.exit_code == 1 and private not in response.output
        assert reason in response.output and str(target) in response.output
        if format == "json":
            report = json.loads(response.output)
            assert not report["passed"]
            assert [(c["scope"], c["status"]) for c in report["checks"]] == [("shell", status), ("integrity", "passed")]
        else:
            assert f"{target}: {status}" in response.output
        assert snapshot(out) == before
    check("failed", "bash rejected script syntax at line 2")
    def cannot_start(*args, **kwargs):
        raise OSError(errno.EACCES, private)
    monkeypatch.setattr("takflow.checks.subprocess.run", cannot_start)
    check("incomplete", "could not start bash")
    monkeypatch.setattr("takflow.checks.subprocess.run", lambda args, **kwargs:
                        subprocess.CompletedProcess(args, -9, b"", private.encode()))
    check("incomplete", "return code -9")


def test_check_on_partial_output_does_not_upgrade_a_failed_build(tmp_path, resources):
    out = tmp_path / "out"
    app = application(resources)
    with app.prepare(data(out, mode="shell")) as ctx:
        first = build(ctx)
        put(resources, "config/config.sh.j2", "{{ unknown }}")
        with pytest.raises(BuildError) as caught:
            build(ctx)
    assert not first.manifest_path.exists() and not caught.value.result.complete
    script = out / "scripts/on/task.sh"
    before = snapshot(out)
    assert check_artifacts(shell=[script]).passed
    assert not first.manifest_path.exists() and snapshot(out) == before


def test_temporary_directory_failure_is_incomplete(tmp_path, resources, monkeypatch):
    with application(resources).prepare(data(tmp_path / "out")) as ctx:
        result = build(ctx)
    before = snapshot(result.output_root)
    def denied(**kwargs):
        raise PermissionError(errno.EACCES, "private-tool-exception")
    monkeypatch.setattr("takflow.artifact_checks.TemporaryDirectory", denied)
    checked = check_artifacts(manifest=result.manifest_path, expand=["/suite/task"], integrity=True)
    assert [c["status"] for c in checked.checks] == ["incomplete", "passed"]
    assert "temporary directory for native expansion: Permission denied" in checked.checks[0]["reason"]
    assert "private-tool-exception" not in repr(checked)
    assert snapshot(result.output_root) == before
