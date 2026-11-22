"""Output-only check contracts, including native job creation with write sentinels."""
import json
import stat

from click.testing import CliRunner
import pytest

from takflow.artifact_checks import check_artifacts
from takflow.build import build
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
