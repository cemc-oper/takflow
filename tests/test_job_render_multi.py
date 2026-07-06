"""Tests for multi-directory job rendering in takflow.job."""
from __future__ import annotations

import pytest

from takflow.config import BaseWorkflowConfig
from takflow.config.workload import ShellWorkload
from takflow.job import render_jobs_from_directory


def _minimal_config() -> BaseWorkflowConfig:
    return BaseWorkflowConfig(
        project_base_dir="/tmp/project",
        run_base_dir="/tmp/run",
        workload=ShellWorkload(),
    )


def test_multi_repo_base_rendering_and_override(tmp_path):
    """Later repo bases overwrite earlier ones; unique files from all layers are kept."""
    base_dir = tmp_path / "base"
    oper_dir = tmp_path / "oper"
    out_dir = tmp_path / "out"

    (base_dir / "jobs").mkdir(parents=True)
    (base_dir / "jobs" / "base_only.sh.j2").write_text("echo base-only")
    (base_dir / "jobs" / "shared.sh.j2").write_text("echo base-shared")
    (base_dir / "jobs" / "uses_partial.sh.j2").write_text(
        '{% include "jobs/partial.sh.j2" %}'
    )
    (base_dir / "jobs" / "partial.sh.j2").write_text("base partial")

    (oper_dir / "jobs").mkdir(parents=True)
    (oper_dir / "jobs" / "oper_only.sh.j2").write_text("echo oper-only")
    (oper_dir / "jobs" / "shared.sh.j2").write_text("echo oper-shared")
    (oper_dir / "jobs" / "partial.sh.j2").write_text("oper partial")

    config = _minimal_config()
    render_jobs_from_directory(
        config=config,
        repo_base=[str(base_dir), str(oper_dir)],
        output_repo_base=str(out_dir),
    )

    assert (out_dir / "jobs" / "base_only.sh").read_text().strip() == "echo base-only"
    assert (out_dir / "jobs" / "oper_only.sh").read_text().strip() == "echo oper-only"
    assert (out_dir / "jobs" / "shared.sh").read_text().strip() == "echo oper-shared"
    # File discovered only in base must use base's own template, not oper's override.
    assert (out_dir / "jobs" / "uses_partial.sh").read_text().strip() == "base partial"


def test_oper_template_falls_back_to_base_include(tmp_path):
    """Oper files can include templates that exist only in the base layer."""
    base_dir = tmp_path / "base"
    oper_dir = tmp_path / "oper"
    out_dir = tmp_path / "out"

    (base_dir / "jobs").mkdir(parents=True)
    (base_dir / "jobs" / "only_in_base.sh.j2").write_text("echo only-in-base")

    (oper_dir / "jobs").mkdir(parents=True)
    (oper_dir / "jobs" / "uses_base_only.sh.j2").write_text(
        '{% include "jobs/only_in_base.sh.j2" %}'
    )

    config = _minimal_config()
    render_jobs_from_directory(
        config=config,
        repo_base=[str(base_dir), str(oper_dir)],
        output_repo_base=str(out_dir),
    )

    assert (
        out_dir / "jobs" / "uses_base_only.sh"
    ).read_text().strip() == "echo only-in-base"


def test_multi_repo_base_skips_missing_jobs_dir(tmp_path):
    """A list entry whose jobs/ directory is missing is skipped."""
    base_dir = tmp_path / "base"
    oper_dir = tmp_path / "oper"  # no jobs/
    out_dir = tmp_path / "out"

    (base_dir / "jobs").mkdir(parents=True)
    (base_dir / "jobs" / "foo.sh.j2").write_text("echo base")

    config = _minimal_config()
    render_jobs_from_directory(
        config=config,
        repo_base=[str(base_dir), str(oper_dir)],
        output_repo_base=str(out_dir),
    )

    assert (out_dir / "jobs" / "foo.sh").read_text().strip() == "echo base"


def test_single_repo_base_missing_jobs_dir_raises(tmp_path):
    """Single-directory mode keeps the original error-on-missing behaviour."""
    config = _minimal_config()
    with pytest.raises(FileNotFoundError):
        render_jobs_from_directory(
            config=config,
            repo_base=str(tmp_path / "missing"),
            output_repo_base=str(tmp_path / "out"),
        )


def test_multi_repo_base_all_missing_raises(tmp_path):
    """If every jobs/ directory is missing, an error is raised."""
    config = _minimal_config()
    with pytest.raises(FileNotFoundError):
        render_jobs_from_directory(
            config=config,
            repo_base=[str(tmp_path / "a"), str(tmp_path / "b")],
            output_repo_base=str(tmp_path / "out"),
        )
