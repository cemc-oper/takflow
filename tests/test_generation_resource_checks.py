"""Resource preflight failures precede writes; reports own actual copied files."""
import hashlib
import os
from pathlib import Path
import stat

import pytest

from takflow.checks import GenerationCheckError, GenerationCheckReport, GenerationInputError
from takflow.build import assets as resource_module
from takflow.build.assets import copy_resource_entries


def write(root, relative, content="resource\n", mode=0o640):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)
    return path


def copy_selected(output, source, *, entries=None, check_report=None):
    if entries is None:
        entries = [(name, name, executable) for name, executable in (
            ("scripts", True), ("utils", True), ("ecflow/include", False), ("takler/include", False)
        ) if (source / name).exists()]
    copy_resource_entries(output, source, entries, check_report=check_report, source_layer="fixture")


def artifact_paths(report):
    return {Path(item["path"]) for item in report.artifacts}


def assert_failure(error, code, stage="resource.preflight"):
    assert error.diagnostic.code == code
    assert error.diagnostic.stage == stage
    assert error.diagnostic.status == "failed"
    assert error.diagnostic.object
    assert error.diagnostic.reason


def test_declared_mappings_copy_files_directories_and_exact_modes(tmp_path):
    source, output = tmp_path / "source", tmp_path / "output"
    files = {
        "scripts/run.sh": write(source, "scripts/run.sh", "#!/bin/sh\nexit 0\n", 0o640),
        "scripts/data.txt": write(source, "scripts/data.txt", "data\n", 0o600),
        "ecflow/include/head.h": write(source, "include/head.h", "# head\n", 0o750),
    }
    report = GenerationCheckReport()
    copy_selected(
        output, source, check_report=report,
        entries=[("scripts", "scripts", True), ("include/head.h", "ecflow/include/head.h", False)],
    )
    expected = {"scripts/run.sh": 0o755, "scripts/data.txt": 0o755, "ecflow/include/head.h": 0o644}
    assert {Path(item["path"]).relative_to(output).as_posix(): int(item["mode"], 8) for item in report.artifacts} == expected
    for relative, mode in expected.items():
        target = output / relative
        assert target.read_bytes() == files[relative].read_bytes()
        assert stat.S_IMODE(target.stat().st_mode) == mode


def test_required_mapping_reports_missing_source_before_copying(tmp_path):
    source, output = tmp_path / "source", tmp_path / "output"
    write(source, "scripts/run.sh")
    with pytest.raises(GenerationInputError) as caught:
        copy_selected(output, source, entries=[("scripts", "scripts", True), ("missing", "include", False)])
    assert_failure(caught.value, "GEN_INPUT_MISSING")
    assert not output.exists()


def test_copy_reports_current_files_content_modes_and_sources(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    inputs = {
        "scripts/run.sh": write(src, "scripts/run.sh", "#!/bin/sh\nexit 0\n"),
        "scripts/data.txt": write(src, "scripts/data.txt", "data\n"),
        "utils/tool.sh": write(src, "utils/tool.sh", "tool\n", 0o600),
        "ecflow/include/head.h": write(src, "ecflow/include/head.h", "head\n", 0o600),
        "takler/include/head.sh": write(src, "takler/include/head.sh", "head\n", 0o640),
    }
    stale = write(output, "scripts/stale.sh", "old\n", 0o600)
    report = GenerationCheckReport()
    copy_selected(output, src, check_report=report)
    assert artifact_paths(report) == {output / relative for relative in inputs}
    for relative, source in inputs.items():
        target = output / relative
        assert target.read_bytes() == source.read_bytes()
        expected = 0o755 if relative.startswith(("scripts/", "utils/")) else 0o644
        assert stat.S_IMODE(target.stat().st_mode) == expected
        recorded = next(item for item in report.artifacts if item["path"] == str(target))
        assert recorded["mode"] == oct(expected)
        assert recorded["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
        assert recorded["role"] == "resource"
        assert (recorded["source"], recorded["layer"]) == (str(source), "fixture")
    assert stat.S_IMODE(stale.stat().st_mode) == 0o600
    assert stale.read_text() == "old\n"
    assert stale not in artifact_paths(report)


def test_disabled_subtrees_do_not_require_valid_sources_or_targets(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/run.sh")
    write(src, "utils", "disabled malformed source\n")
    disabled_target = write(output, "utils", "old disabled target\n")
    copy_selected(output, src, entries=[("scripts", "scripts", True)])
    assert disabled_target.read_text() == "old disabled target\n"
    assert (output / "scripts/run.sh").is_file()


def test_missing_source_fails_without_creating_output(tmp_path):
    src, output = tmp_path / "missing", tmp_path / "output"
    with pytest.raises(GenerationInputError) as caught:
        copy_selected(output, src)
    assert isinstance(caught.value, FileNotFoundError)
    assert_failure(caught.value, "RESOURCE_SOURCE_MISSING")
    assert not output.exists()
    assert caught.value.report.artifacts == []


def test_source_path_must_be_directory_before_output_creation(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    src.write_text("file\n")
    with pytest.raises(GenerationCheckError) as caught:
        copy_selected(output, src)
    assert_failure(caught.value, "RESOURCE_SOURCE_TYPE")
    assert not output.exists()


@pytest.mark.parametrize("location", ["root", "parent", "subtree", "leaf"])
def test_output_type_conflicts_precede_every_copy(tmp_path, location):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/run.sh", "new script\n")
    write(src, "utils/tool.sh", "new utility\n")
    if location == "root":
        sentinel = write(tmp_path, "output", "old file\n")
        code = "RESOURCE_OUTPUT_TYPE"
    elif location == "parent":
        sentinel = write(tmp_path, "output", "old file\n")
        output = output / "child"
        code = "RESOURCE_OUTPUT_TYPE"
    else:
        sentinel = write(output, "scripts/run.sh", "old script\n", 0o600)
        if location == "subtree":
            write(output, "utils", "wrong subtree type\n")
            code = "RESOURCE_OUTPUT_TYPE"
        else:
            (output / "utils/tool.sh").mkdir(parents=True)
            code = "GEN_OUTPUT_NOT_FILE"
    before = sentinel.read_bytes(), stat.S_IMODE(sentinel.stat().st_mode)
    with pytest.raises(GenerationCheckError) as caught:
        copy_selected(output, src)
    assert_failure(caught.value, code)
    assert (sentinel.read_bytes(), stat.S_IMODE(sentinel.stat().st_mode)) == before
    assert caught.value.report.artifacts == []


@pytest.mark.parametrize("suffix", ["", "scripts/build"])
def test_recursive_or_same_tree_copy_is_rejected(tmp_path, suffix):
    src = tmp_path / "src"
    original = write(src, "scripts/run.sh", "source\n")
    output = src / suffix
    with pytest.raises(GenerationCheckError) as caught:
        copy_selected(output, src)
    assert_failure(caught.value, "RESOURCE_COPY_OVERLAP")
    assert original.read_text() == "source\n"
    if suffix:
        assert not output.exists()


def test_output_under_unselected_part_of_source_root_is_safe(tmp_path):
    src = tmp_path / "src"
    write(src, "scripts/run.sh")
    output = src / "build"
    copy_selected(output, src)
    assert (output / "scripts/run.sh").is_file()
    assert not (output / "scripts/build").exists()


def test_resolved_output_alias_cannot_hide_recursive_copy(tmp_path):
    src = tmp_path / "src"
    write(src, "scripts/run.sh")
    alias = tmp_path / "output-alias"
    alias.symlink_to(src / "scripts", target_is_directory=True)
    with pytest.raises(GenerationCheckError) as caught:
        copy_selected(alias, src)
    assert_failure(caught.value, "RESOURCE_COPY_OVERLAP")
    assert not (src / "scripts/scripts").exists()


def test_source_links_within_the_layer_are_copied(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    external_file = write(src, "shared/shared.sh", "shared\n")
    external_tree = src / "shared-tree"
    write(external_tree, "nested/tool.sh", "tool\n", 0o600)
    scripts = src / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "linked.sh").symlink_to(external_file)
    (scripts / "linked-tree").symlink_to(external_tree, target_is_directory=True)
    report = GenerationCheckReport()
    copy_selected(output, src, check_report=report)
    assert (output / "scripts/linked.sh").read_text() == "shared\n"
    assert not (output / "scripts/linked.sh").is_symlink()
    assert (output / "scripts/linked-tree/nested/tool.sh").read_text() == "tool\n"
    assert artifact_paths(report) == {output / "scripts/linked.sh",
                                      output / "scripts/linked-tree/nested/tool.sh"}


def test_source_directory_link_cycle_fails_before_copy(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/sub/run.sh")
    (src / "scripts/sub/back").symlink_to(src / "scripts", target_is_directory=True)
    with pytest.raises(GenerationCheckError) as caught:
        copy_selected(output, src)
    assert_failure(caught.value, "RESOURCE_SOURCE_CYCLE")
    assert not output.exists()


def test_source_link_to_output_cannot_reintroduce_recursion(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/run.sh")
    sentinel = write(output, "sentinel", "old\n")
    (src / "scripts/output-link").symlink_to(output, target_is_directory=True)
    with pytest.raises(GenerationCheckError) as caught:
        copy_selected(output, src)
    assert_failure(caught.value, "GEN_PATH_ESCAPE")
    assert list(output.iterdir()) == [sentinel]


def test_source_file_link_cannot_read_an_output_overwritten_by_another_copy(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/a.sh", "new\n")
    sentinel = write(output, "scripts/a.sh", "old\n")
    (src / "scripts/b.sh").symlink_to(sentinel)
    with pytest.raises(GenerationCheckError) as caught:
        copy_selected(output, src)
    assert_failure(caught.value, "GEN_PATH_ESCAPE")
    assert sentinel.read_text() == "old\n"
    assert not (output / "scripts/b.sh").exists()


@pytest.mark.parametrize("link_kind", ["tree", "file"])
def test_destination_links_cannot_write_outside_output_root(tmp_path, link_kind):
    src, output, external = tmp_path / "src", tmp_path / "output", tmp_path / "external"
    write(src, "scripts/run.sh", "new\n")
    sentinel = write(external, "run.sh", "external old\n")
    output.mkdir()
    if link_kind == "tree":
        (output / "scripts").symlink_to(external, target_is_directory=True)
    else:
        (output / "scripts").mkdir()
        (output / "scripts/run.sh").symlink_to(sentinel)
    with pytest.raises(GenerationCheckError) as caught:
        copy_selected(output, src)
    assert_failure(caught.value, "GEN_PATH_ESCAPE")
    assert sentinel.read_text() == "external old\n"


def test_existing_hardlink_to_source_is_rejected_without_chmod(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    source = write(src, "scripts/run.sh")
    target = output / "scripts/run.sh"
    target.parent.mkdir(parents=True)
    os.link(source, target)
    with pytest.raises(GenerationCheckError) as caught:
        copy_selected(output, src)
    assert_failure(caught.value, "RESOURCE_COPY_OVERLAP")
    assert stat.S_IMODE(source.stat().st_mode) == 0o640


def test_destination_aliases_cannot_overwrite_two_artifacts_at_one_location(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/a.sh", "a\n")
    write(src, "scripts/b.sh", "b\n")
    sentinel = write(output, "scripts/b.sh", "old\n", 0o600)
    (output / "scripts/a.sh").symlink_to(sentinel)
    with pytest.raises(GenerationCheckError) as caught:
        copy_selected(output, src)
    assert_failure(caught.value, "RESOURCE_OUTPUT_COLLISION")
    assert sentinel.read_text() == "old\n"
    assert stat.S_IMODE(sentinel.stat().st_mode) == 0o600
    assert caught.value.report.artifacts == []


def test_cross_file_hardlinks_cannot_modify_a_later_resource_input(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/a.sh", "a\n")
    later_source = write(src, "scripts/b.sh", "b\n")
    earlier_target = output / "scripts/a.sh"
    earlier_target.parent.mkdir(parents=True)
    os.link(later_source, earlier_target)
    with pytest.raises(GenerationCheckError) as caught:
        copy_selected(output, src)
    assert_failure(caught.value, "RESOURCE_COPY_OVERLAP")
    assert later_source.read_text() == "b\n"
    assert not (output / "scripts/b.sh").exists()


def test_existing_hardlinked_outputs_cannot_alias_two_planned_files(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/a.sh", "a\n")
    write(src, "scripts/b.sh", "b\n")
    sentinel = write(output, "scripts/a.sh", "old\n")
    os.link(sentinel, output / "scripts/b.sh")
    with pytest.raises(GenerationCheckError) as caught:
        copy_selected(output, src)
    assert_failure(caught.value, "RESOURCE_OUTPUT_COLLISION")
    assert sentinel.read_text() == "old\n"


@pytest.mark.parametrize("kind", ["source_file", "source_directory", "target_file", "target_parent"])
def test_permission_failure_is_preflight_and_preserves_existing_files(tmp_path, kind):
    src, output = tmp_path / "src", tmp_path / "output"
    source = write(src, "scripts/run.sh")
    sentinel = write(output, "scripts/run.sh", "old\n")
    if kind == "source_file":
        source.chmod(0)
        code = "GEN_INPUT_UNREADABLE"
    elif kind == "source_directory":
        source.parent.chmod(0)
        code = "RESOURCE_SOURCE_PERMISSION"
    elif kind == "target_file":
        sentinel.chmod(0o444)
        code = "GEN_OUTPUT_NOT_WRITABLE"
    else:
        sentinel.parent.chmod(0o555)
        code = "GEN_OUTPUT_NOT_WRITABLE"
    try:
        with pytest.raises(GenerationCheckError) as caught:
            copy_selected(output, src)
        assert_failure(caught.value, code)
        assert sentinel.read_text() == "old\n"
        assert caught.value.report.artifacts == []
    finally:
        source.parent.chmod(0o755)
        sentinel.parent.chmod(0o755)


def test_copy_failure_preserves_original_and_completed_outputs(tmp_path, monkeypatch):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/a.sh")
    write(src, "scripts/b.sh")
    stale = write(output, "scripts/stale.sh", "old\n")
    original_copy = resource_module.shutil.copy2
    error = OSError("simulated copy failure")
    report = GenerationCheckReport()

    def fail_second(source, target):
        if source.name == "b.sh":
            raise error
        return original_copy(source, target)

    monkeypatch.setattr(resource_module.shutil, "copy2", fail_second)
    with pytest.raises(OSError) as caught:
        copy_selected(output, src, check_report=report)
    assert caught.value is error
    assert any(item.code == "RESOURCE_COPY_FAILED" and item.stage == "resource.copy" for item in report.checks)
    assert artifact_paths(report) == {output / "scripts/a.sh"}
    assert stale.read_text() == "old\n"


def test_permission_failure_records_the_written_partial_file(tmp_path, monkeypatch):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/run.sh")
    target = output / "scripts/run.sh"
    original_chmod = Path.chmod
    error = OSError("simulated chmod failure")
    report = GenerationCheckReport()

    def fail(path, mode, **kwargs):
        if path == target:
            raise error
        return original_chmod(path, mode, **kwargs)

    monkeypatch.setattr(Path, "chmod", fail)
    with pytest.raises(OSError) as caught:
        copy_selected(output, src, check_report=report)
    assert caught.value is error
    item, = report.artifacts
    assert (item["path"], item["role"], item["mode"]) == (str(target), "resource_partial", "0o640")


def test_copy_uses_the_validated_selection_when_the_source_gains_files(tmp_path, monkeypatch):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/run.sh")
    original_copy = resource_module.shutil.copy2
    report = GenerationCheckReport()

    def add_file_before_copy(source, target):
        write(src, "scripts/new.txt", "appeared after preflight\n")
        return original_copy(source, target)

    monkeypatch.setattr(resource_module.shutil, "copy2", add_file_before_copy)
    copy_selected(output, src, check_report=report)
    assert artifact_paths(report) == {output / "scripts/run.sh"}
    assert not (output / "scripts/new.txt").exists()
