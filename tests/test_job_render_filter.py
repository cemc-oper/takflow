"""Tests for template_filter (feature-toggle-aware rendering) in takflow.toolkit.job."""
from __future__ import annotations

from pathlib import Path

from takflow.config import BaseWorkflowConfig
from takflow.config.workload import ShellWorkload
from takflow.toolkit import render_jobs_from_directory


def _minimal_config() -> BaseWorkflowConfig:
    return BaseWorkflowConfig(
        project_base_dir="/tmp/project",
        run_base_dir="/tmp/run",
        workload=ShellWorkload(),
    )


def _write_jobs(repo: Path, files: dict) -> Path:
    jobs_dir = repo / "jobs"
    for rel, content in files.items():
        path = jobs_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return jobs_dir


def test_template_filter_skips_disabled_component(tmp_path):
    """Templates under a disabled component subtree are not rendered."""
    repo = tmp_path / "repo"
    out_dir = tmp_path / "out"
    _write_jobs(
        repo,
        {
            "model/grapes.sh.j2": "echo model",
            "data/initial.sh.j2": "echo data",
            "data/grib2_orig.sh.j2": "echo data2",
            "housekeep_final.sh.j2": "echo hk",
        },
    )

    render_jobs_from_directory(
        config=_minimal_config(),
        repo_base=str(repo),
        output_repo_base=str(out_dir),
        template_filter=lambda rel: rel.parts[0] != "data",
    )

    assert (out_dir / "jobs" / "model" / "grapes.sh").exists()
    assert (out_dir / "jobs" / "housekeep_final.sh").exists()
    assert not (out_dir / "jobs" / "data").exists()


def test_template_filter_none_renders_everything(tmp_path):
    """Default (no filter) renders every template — unchanged legacy behaviour."""
    repo = tmp_path / "repo"
    out_dir = tmp_path / "out"
    _write_jobs(
        repo,
        {
            "model/grapes.sh.j2": "echo model",
            "data/initial.sh.j2": "echo data",
            "housekeep_final.sh.j2": "echo hk",
        },
    )

    render_jobs_from_directory(
        config=_minimal_config(),
        repo_base=str(repo),
        output_repo_base=str(out_dir),
    )

    assert (out_dir / "jobs" / "model" / "grapes.sh").exists()
    assert (out_dir / "jobs" / "data" / "initial.sh").exists()
    assert (out_dir / "jobs" / "housekeep_final.sh").exists()


def test_template_filter_receives_jobs_relative_path(tmp_path):
    """The predicate receives paths relative to jobs/, not to the repo root."""
    repo = tmp_path / "repo"
    out_dir = tmp_path / "out"
    _write_jobs(repo, {"data/sub/initial.sh.j2": "echo x", "top.sh.j2": "echo y"})

    seen = []
    render_jobs_from_directory(
        config=_minimal_config(),
        repo_base=str(repo),
        output_repo_base=str(out_dir),
        template_filter=lambda rel: seen.append(rel) or True,
    )

    assert set(seen) == {Path("data/sub/initial.sh.j2"), Path("top.sh.j2")}
    assert not any(str(p).startswith("jobs") for p in seen)


def test_template_filter_applies_to_every_repo_layer(tmp_path):
    """Filtering applies per layer: an oper-layer override of a disabled
    template is skipped as well (filter acts on the jobs-relative path,
    orthogonal to the layer/override order)."""
    base_dir = tmp_path / "base"
    oper_dir = tmp_path / "oper"
    out_dir = tmp_path / "out"

    _write_jobs(base_dir, {"model/a.sh.j2": "echo base-a", "data/b.sh.j2": "echo base-b"})
    _write_jobs(oper_dir, {"data/b.sh.j2": "echo oper-b", "oper_only.sh.j2": "echo oper"})

    render_jobs_from_directory(
        config=_minimal_config(),
        repo_base=[str(base_dir), str(oper_dir)],
        output_repo_base=str(out_dir),
        template_filter=lambda rel: rel.parts[0] != "data",
    )

    assert (out_dir / "jobs" / "model" / "a.sh").exists()
    assert (out_dir / "jobs" / "oper_only.sh").exists()
    assert not (out_dir / "jobs" / "data").exists()
