"""Resource preflight failures precede writes; reports own actual copied files."""
import hashlib
import os
from pathlib import Path
import stat

import pytest

from takflow.checks import GenerationCheckError, GenerationCheckReport, GenerationInputError
from takflow.toolkit import copy_resources_to_output
from takflow.toolkit import resource as resource_module


def write(root, relative, content="resource\n", mode=0o640):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)
    return path


def artifact_paths(report):
    return {Path(item["path"]) for item in report.artifacts}


def assert_failure(error, code, stage="resource.preflight"):
    assert error.diagnostic.code == code
    assert error.diagnostic.stage == stage
    assert error.diagnostic.status == "failed"
    assert error.diagnostic.object
    assert error.diagnostic.reason


def test_additional_directory_mappings_preserve_legacy_copy_contract(tmp_path):
    source, output = tmp_path / "source", tmp_path / "output"
    files = {
        "scripts/run.sh": write(source, "scripts/run.sh", "#!/bin/sh\nexit 0\n", 0o640),
        "scripts/data.txt": write(source, "scripts/data.txt", "data\n", 0o600),
        "include/head.h": write(source, "include/head.h", "# head\n", 0o750),
    }
    report = GenerationCheckReport()
    copy_resources_to_output(
        output, source, check_report=report,
        additional_entries=(("include", "ecflow/include", False),),
    )
    expected = {"scripts/run.sh": 0o751, "scripts/data.txt": 0o600, "ecflow/include/head.h": 0o750}
    assert {Path(item["path"]).relative_to(output).as_posix(): int(item["mode"], 8) for item in report.artifacts} == expected
    for relative, mode in expected.items():
        target = output / relative
        original = files[relative.replace("ecflow/", "")]
        assert target.read_bytes() == original.read_bytes()
        assert stat.S_IMODE(target.stat().st_mode) == mode


@pytest.mark.parametrize("kind", ["file", "missing"])
def test_additional_directory_mappings_reject_invalid_sources_before_copying(tmp_path, kind):
    source, output = tmp_path / "source", tmp_path / "output"
    write(source, "scripts/run.sh")
    if kind == "file":
        write(source, "include", "invalid directory\n")
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(output, source, additional_entries=(("include", "include", False),))
    assert_failure(caught.value, "RESOURCE_SOURCE_TYPE" if kind == "file" else "RESOURCE_SOURCE_MISSING")
    assert not output.exists()


def test_copy_preserves_bytes_modes_return_and_reports_only_current_files(tmp_path):
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
    assert copy_resources_to_output(output, src, check_report=report) is None
    assert artifact_paths(report) == {output / relative for relative in inputs}
    for relative, source in inputs.items():
        target = output / relative
        assert target.read_bytes() == source.read_bytes()
        expected = stat.S_IMODE(source.stat().st_mode)
        if relative.startswith(("scripts/", "utils/")) and relative.endswith(".sh"):
            expected |= 0o111
        assert stat.S_IMODE(target.stat().st_mode) == expected
        recorded = next(item for item in report.artifacts if item["path"] == str(target))
        assert recorded["mode"] == oct(expected)
        assert recorded["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
        assert recorded["role"] == "resource"
    # The old public helper still grants execute bits to existing *.sh files.
    assert stat.S_IMODE(stale.stat().st_mode) == 0o711
    assert stale.read_text() == "old\n"
    assert stale not in artifact_paths(report)
    assert any(item.code == "RESOURCE_RUNTIME_REFERENCES" and item.status == "unchecked"
               for item in report.checks)


def test_absent_optional_subtrees_still_create_empty_output(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    src.mkdir()
    report = GenerationCheckReport()
    assert copy_resources_to_output(output, src, check_report=report) is None
    assert output.is_dir()
    assert list(output.iterdir()) == []
    assert report.artifacts == []


def test_disabled_subtrees_do_not_require_valid_sources_or_targets(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/run.sh")
    write(src, "utils", "disabled malformed source\n")
    disabled_target = write(output, "utils", "old disabled target\n")
    copy_resources_to_output(output, src, include_utils=False)
    assert disabled_target.read_text() == "old disabled target\n"
    assert (output / "scripts/run.sh").is_file()


def test_missing_source_fails_without_creating_output(tmp_path):
    src, output = tmp_path / "missing", tmp_path / "output"
    with pytest.raises(GenerationInputError) as caught:
        copy_resources_to_output(output, src)
    assert isinstance(caught.value, FileNotFoundError)
    assert_failure(caught.value, "RESOURCE_SOURCE_MISSING")
    assert not output.exists()
    assert caught.value.report.artifacts == []


@pytest.mark.parametrize("location", ["root", "scripts"])
def test_source_path_must_be_directory_before_output_creation(tmp_path, location):
    src, output = tmp_path / "src", tmp_path / "output"
    if location == "root":
        src.write_text("file\n")
    else:
        write(src, "scripts", "file\n")
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(output, src)
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
        copy_resources_to_output(output, src)
    assert_failure(caught.value, code)
    assert (sentinel.read_bytes(), stat.S_IMODE(sentinel.stat().st_mode)) == before
    assert caught.value.report.artifacts == []


@pytest.mark.parametrize("suffix", ["", "scripts/build"])
def test_recursive_or_same_tree_copy_is_rejected(tmp_path, suffix):
    src = tmp_path / "src"
    original = write(src, "scripts/run.sh", "source\n")
    output = src / suffix
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(output, src)
    assert_failure(caught.value, "RESOURCE_COPY_OVERLAP")
    assert original.read_text() == "source\n"
    if suffix:
        assert not output.exists()


def test_output_under_unselected_part_of_source_root_is_safe(tmp_path):
    src = tmp_path / "src"
    write(src, "scripts/run.sh")
    output = src / "build"
    copy_resources_to_output(output, src)
    assert (output / "scripts/run.sh").is_file()
    assert not (output / "scripts/build").exists()


def test_resolved_output_alias_cannot_hide_recursive_copy(tmp_path):
    src = tmp_path / "src"
    write(src, "scripts/run.sh")
    alias = tmp_path / "output-alias"
    alias.symlink_to(src / "scripts", target_is_directory=True)
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(alias, src)
    assert_failure(caught.value, "RESOURCE_COPY_OVERLAP")
    assert not (src / "scripts/scripts").exists()


def test_safe_source_links_keep_copytree_following_semantics(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    external_file = write(tmp_path, "external/shared.sh", "shared\n")
    external_tree = tmp_path / "external-tree"
    write(external_tree, "nested/tool.sh", "tool\n", 0o600)
    scripts = src / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "linked.sh").symlink_to(external_file)
    (scripts / "linked-tree").symlink_to(external_tree, target_is_directory=True)
    report = GenerationCheckReport()
    copy_resources_to_output(output, src, check_report=report)
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
        copy_resources_to_output(output, src)
    assert_failure(caught.value, "RESOURCE_SOURCE_CYCLE")
    assert not output.exists()


def test_source_link_to_output_cannot_reintroduce_recursion(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/run.sh")
    sentinel = write(output, "sentinel", "old\n")
    (src / "scripts/output-link").symlink_to(output, target_is_directory=True)
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(output, src)
    assert_failure(caught.value, "RESOURCE_COPY_OVERLAP")
    assert list(output.iterdir()) == [sentinel]


def test_source_file_link_cannot_read_an_output_overwritten_by_another_copy(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/a.sh", "new\n")
    sentinel = write(output, "scripts/a.sh", "old\n")
    (src / "scripts/b.sh").symlink_to(sentinel)
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(output, src)
    assert_failure(caught.value, "RESOURCE_COPY_OVERLAP")
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
        copy_resources_to_output(output, src)
    assert_failure(caught.value, "GEN_PATH_ESCAPE")
    assert sentinel.read_text() == "external old\n"


def test_existing_hardlink_to_source_is_rejected_without_chmod(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    source = write(src, "scripts/run.sh")
    target = output / "scripts/run.sh"
    target.parent.mkdir(parents=True)
    os.link(source, target)
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(output, src)
    assert_failure(caught.value, "RESOURCE_COPY_OVERLAP")
    assert stat.S_IMODE(source.stat().st_mode) == 0o640


def test_destination_aliases_cannot_overwrite_two_artifacts_at_one_location(tmp_path):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/a.sh", "a\n")
    write(src, "scripts/b.sh", "b\n")
    sentinel = write(output, "scripts/b.sh", "old\n", 0o600)
    (output / "scripts/a.sh").symlink_to(sentinel)
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(output, src)
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
        copy_resources_to_output(output, src)
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
        copy_resources_to_output(output, src)
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
            copy_resources_to_output(output, src)
        assert_failure(caught.value, code)
        assert sentinel.read_text() == "old\n"
        assert caught.value.report.artifacts == []
    finally:
        source.parent.chmod(0o755)
        sentinel.parent.chmod(0o755)


def test_postcopy_content_failure_reports_written_file_and_stops_next_tree(tmp_path, monkeypatch):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/run.sh", "original\n")
    write(src, "utils/tool.sh")
    original_copy = resource_module.shutil.copy2

    def corrupt(source, target):
        result = original_copy(source, target)
        Path(target).write_text("corrupted\n")
        return result

    monkeypatch.setattr(resource_module.shutil, "copy2", corrupt)
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(output, src)
    assert_failure(caught.value, "RESOURCE_CONTENT_MISMATCH", "resource.check")
    assert (output / "scripts/run.sh").read_text() == "corrupted\n"
    assert artifact_paths(caught.value.report) == {output / "scripts/run.sh"}
    assert not (output / "utils").exists()


def test_postcopy_permission_failure_retains_actual_mode(tmp_path, monkeypatch):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/run.sh")
    monkeypatch.setattr(resource_module, "make_scripts_executable", lambda path: None)
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(output, src)
    assert_failure(caught.value, "RESOURCE_PERMISSION_MISMATCH", "resource.check")
    assert caught.value.report.artifacts[0]["mode"] == "0o640"


def test_copy_failure_records_only_files_completed_by_this_invocation(tmp_path, monkeypatch):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/a.sh")
    write(src, "scripts/b.sh")
    stale = write(output, "scripts/stale.sh", "old\n")
    original_copy = resource_module.shutil.copy2
    completed = []

    def fail_second(source, target):
        if completed:
            raise OSError("simulated copy failure")
        result = original_copy(source, target)
        completed.append(Path(target))
        return result

    monkeypatch.setattr(resource_module.shutil, "copy2", fail_second)
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(output, src)
    assert_failure(caught.value, "RESOURCE_COPY_FAILED", "resource.copy")
    assert artifact_paths(caught.value.report) == set(completed)
    assert stale not in artifact_paths(caught.value.report)
    assert stale.read_text() == "old\n"


def test_partial_file_disappearing_does_not_mask_primary_copy_failure(tmp_path, monkeypatch):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/a.sh")
    write(src, "scripts/b.sh")
    original_copy = resource_module.shutil.copy2
    completed = []

    def delete_completed_then_fail(source, target):
        if completed:
            completed[0].unlink()
            raise OSError("primary copy failure")
        result = original_copy(source, target)
        completed.append(Path(target))
        return result

    monkeypatch.setattr(resource_module.shutil, "copy2", delete_completed_then_fail)
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(output, src)
    assert_failure(caught.value, "RESOURCE_COPY_FAILED", "resource.copy")
    report = caught.value.report
    assert next(item for item in report.checks if item.status == "failed").code == "RESOURCE_COPY_FAILED"
    assert report.artifacts == []
    assert any(item.code == "RESOURCE_ARTIFACT_UNAVAILABLE" and item.status == "unchecked"
               for item in report.checks)


def test_source_selection_change_is_reported_with_actual_outputs(tmp_path, monkeypatch):
    src, output = tmp_path / "src", tmp_path / "output"
    write(src, "scripts/run.sh")
    original_copytree = resource_module.shutil.copytree
    introduced = False

    def add_file_before_copy(source, target, **kwargs):
        nonlocal introduced
        if not introduced:
            introduced = True
            write(src, "scripts/new.txt", "appeared after preflight\n")
        return original_copytree(source, target, **kwargs)

    monkeypatch.setattr(resource_module.shutil, "copytree", add_file_before_copy)
    with pytest.raises(GenerationCheckError) as caught:
        copy_resources_to_output(output, src)
    assert_failure(caught.value, "RESOURCE_SOURCE_CHANGED", "resource.check")
    assert artifact_paths(caught.value.report) == {output / "scripts/run.sh", output / "scripts/new.txt"}
