"""Select Jinja job templates and write their rendered files."""
from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Union

from jinja2 import Environment, FileSystemLoader, TemplateError

from takflow._files import io_failure_reason
from takflow.build_info import _current_build_info_lines
from takflow.checks import (
    GenerationCheckReport,
    GenerationCheckError,
    GenerationInputError,
    check_input_file,
    check_output_path,
    check_relative_path,
    preflight_generation,
)
from takflow.checks.diagnostics import template_failure
from takflow.jobs.headers import RESOURCE_TEMPLATE_HELPERS
from takflow.jobs.provenance import job_source, prepared_source, resource_source
from takflow.jobs.scripts import _script_template_helpers

if TYPE_CHECKING:
    from takflow.config import BaseWorkflowConfig


def _template_file(env: Environment, name: str) -> Optional[Path]:
    if isinstance(env.loader, FileSystemLoader):
        return next((Path(root, name) for root in env.loader.searchpath
                     if Path(root, name).is_file()), None)
    return None


class _JobTemplateLoader(FileSystemLoader):
    """Guard files selected by real Jinja control flow before reading them."""

    def __init__(self, search_paths, report: GenerationCheckReport):
        super().__init__(search_paths)
        self._report = report

    def get_source(self, environment: Environment, template: str):
        if Path(template).is_absolute() or ".." in Path(template).parts:
            self._report.fail("GEN_PATH_ESCAPE", "job.render", template, "template reference must stay within its resource roots")
        for root in self.searchpath:
            candidate = Path(root, template)
            if os.path.lexists(candidate):
                path = check_relative_path(root, template, stage="job.render", report=self._report)
                check_input_file(path, stage="job.render", report=self._report)
                break
        return super().get_source(environment, template)


def _job_input_guard(outputs, report: GenerationCheckReport):
    """Index selected destinations once, then check each template or script as it is used."""
    paths = {path.resolve() for path in outputs}
    identities = {}
    for path in paths:
        if path.is_file():
            metadata = path.stat()
            identities[(metadata.st_dev, metadata.st_ino)] = path

    def protect(source: Path) -> None:
        resolved = source.resolve()
        target = resolved if resolved in paths else None
        if target is None and identities and source.is_file():
            metadata = source.stat()
            target = identities.get((metadata.st_dev, metadata.st_ino))
        if target is not None:
            report.fail("GEN_INPUT_OUTPUT_OVERLAP", "job.preflight", str(target),
                        "job output would overwrite a known template or script input")

    return protect


def render_jobs_from_directory(
    config: "BaseWorkflowConfig",
    repo_base: Union[str, Path, List[Union[str, Path]]],
    output_repo_base: str,
    job_output_dir: str = "jobs",
    template_filter: Optional[Callable[[Path], bool]] = None,
    *,
    check_report: Optional[GenerationCheckReport] = None,
    environment: Environment | None = None,
    template_context: Mapping | None = None,
    file_mode: int | None = None,
    verbose: bool = True,
    script_input_check: Callable[[str], None] | None = None,
    prepare_outputs: Callable[[list[tuple[Path, Path]]], None] | None = None,
    source_layers: tuple[tuple[str, Path], ...] | None = None,
    script_source: Callable[[Path, bytes], str] | None = None,
) -> None:
    """Render every ``jobs/**/*.j2`` template under one or more repo roots.

    Parameters
    ----------
    config : BaseWorkflowConfig
        Workflow config used as template data.
    repo_base : str, Path, or list
        One or more repo roots containing ``jobs`` template directories.
        When a list is given, directories are processed in order and later
        directories overwrite earlier ones for identical relative paths.
    output_repo_base : str
        Output repo root.
    job_output_dir : str
        Output subdirectory for rendered job files, relative to
        ``output_repo_base``. The default ``"jobs"`` reproduces the source
        layout (``jobs/<rel>.j2`` -> ``jobs/<rel>.<suffix>``); apps whose
        runtime layout differs (e.g. TYM's ``ecffiles/``) pass their own
        directory name.
    template_filter : callable, optional
        Predicate receiving the template's path relative to its ``jobs/``
        directory (e.g. ``Path("data/initial.sh.j2")``); returning ``False``
        skips the template entirely (no rendering, no output file). Intended
        for feature-toggle-aware generation: apps pass a predicate derived
        from their ``enable_*`` switches so templates of disabled components
        never enter rendering. ``None`` (default) renders everything —
        identical to the previous behaviour.
    check_report : GenerationCheckReport, optional
        Collect generation failures and files written by this invocation.
    script_input_check : callable, optional
        Additional validation of local scripts actually consumed while rendering.
        The standard full build uses this to reject stale prerequisite files.
    """
    report = check_report if check_report is not None else GenerationCheckReport()
    preflight_generation(config, check_report=report)
    if isinstance(repo_base, (str, Path)):
        repo_bases = [str(repo_base)]
    elif isinstance(repo_base, (list, tuple)):
        repo_bases = [str(rb) for rb in repo_base]
    else:
        raise TypeError(
            f"repo_base must be str, Path, or list, got {type(repo_base)}"
        )
    if source_layers is None:
        source_layers = tuple((Path(base).absolute().name, Path(base)) for base in repo_bases)
    if script_source is None:
        def script_source(path: Path, content: bytes) -> str:
            return prepared_source(path, content, source_layers, Path(output_repo_base).absolute(), ((".", "."),))

    # Collect existing (repo_base, jobs_dir) pairs.  For a single repo_base we
    # preserve the original error-on-missing behaviour; for a list we tolerate
    # sparse layers but fail if nothing is found.
    repo_jobs_pairs = []
    for source_idx, rb in enumerate(repo_bases):
        jobs_dir = Path(rb, "jobs")
        if jobs_dir.is_dir():
            repo_jobs_pairs.append((source_idx, rb, jobs_dir))
        elif len(repo_bases) == 1:
            report.fail("GEN_JOB_DIRECTORY_MISSING", "job.preflight", str(jobs_dir),
                        "jobs directory is unavailable", error_type=GenerationInputError)

    if not repo_jobs_pairs:
        report.fail("GEN_JOB_DIRECTORY_MISSING", "job.preflight", "jobs",
                    "no jobs directory is available in the resource layers",
                    error_type=GenerationInputError)

    # The guard is populated from the planned destinations before rendering.
    script_helpers = _script_template_helpers(
        config, output_repo_base, report,
        protect_input=lambda path: protect_input(path),
        script_input_check=script_input_check,
        script_source=script_source,
        legacy_renderer=environment is None,
    )

    def build_environment(source_idx: int) -> Environment:
        """Build a Jinja2 env where the current source repo has highest priority.

        Search order: current source, then earlier layers in reverse rendering
        order (more specialised layers first).
        """
        source_repo_base = repo_bases[source_idx]
        search_paths = [source_repo_base]
        if source_idx > 0:
            search_paths.extend(repo_bases[source_idx - 1::-1])

        env = environment if environment is not None else Environment(
            loader=_JobTemplateLoader(search_paths, report),
            lstrip_blocks=True,
            trim_blocks=True,
        )
        env.globals.update(script_helpers)
        env.globals.update(RESOURCE_TEMPLATE_HELPERS)
        return env

    if config.workflow_mode == "shell":
        output_file_suffix = "sh"
    elif config.workflow_mode == "ecflow":
        output_file_suffix = "ecf"
    elif config.workflow_mode == "takler":
        output_file_suffix = "sh"
    else:
        output_file_suffix = "sh"

    planned = []
    destinations = {}
    for source_idx, repo_base_str, jobs_dir in repo_jobs_pairs:
        env = build_environment(source_idx)
        j2_files = sorted(jobs_dir.rglob("*.j2"))
        for j2_file in j2_files:
            relative_path = j2_file.relative_to(repo_base_str)
            jobs_relative_path = j2_file.relative_to(jobs_dir)

            if template_filter is not None and not template_filter(jobs_relative_path):
                if verbose:
                    print(f"Skipped (disabled): {jobs_relative_path}")
                continue

            if jobs_relative_path.stem.endswith(".sh"):
                base_name = jobs_relative_path.stem[:-3]
            else:
                base_name = jobs_relative_path.stem

            output_file_relative_path = Path(
                job_output_dir,
                jobs_relative_path.parent,
                f"{base_name}.{output_file_suffix}",
            )
            destination = check_relative_path(output_repo_base, output_file_relative_path,
                                               stage="job.preflight", report=report)
            check_output_path(destination, stage="job.preflight", report=report)
            resolved = destination.resolve()
            for previous, previous_template in destinations.items():
                if resolved == previous and relative_path == previous_template:
                    continue  # Declared later-layer override of the same template.
                if resolved == previous or resolved in previous.parents or previous in resolved.parents:
                    report.fail("GEN_JOB_NAME_COLLISION", "job.preflight",
                                output_file_relative_path.as_posix(),
                                "different job templates map to conflicting output paths")
            destinations[resolved] = relative_path
            planned.append((env, relative_path, output_file_relative_path))

    if environment is not None:
        # The supplied standard loader searches the final effective layer set.
        # Shadowed templates must neither render nor fail on obsolete inputs.
        planned = list({destination: (env, relative, destination)
                        for env, relative, destination in planned}.values())
    files = [(source, Path(output_repo_base, target))
             for env, relative, target in planned
             if (source := _template_file(env, relative.as_posix())) is not None]
    protect_input = _job_input_guard(destinations, report)
    for source, _ in files:
        protect_input(source)
    if prepare_outputs is not None:
        prepare_outputs(files)

    for env, relative_path, output_file_relative_path in planned:
        _render_single_job_file(
            relative_path=relative_path,
            output_repo_base=output_repo_base,
            output_relative_path=output_file_relative_path,
            config=config,
            env=env,
            report=report,
            template_context=template_context,
            file_mode=file_mode,
            source_layers=source_layers,
        )

        if verbose:
            print(f"Generated: {output_file_relative_path}")


def render_single_job_file(
    relative_path: Path,
    output_repo_base: str,
    output_relative_path: Path,
    config: "BaseWorkflowConfig",
    env: Environment,
    *,
    check_report: Optional[GenerationCheckReport] = None,
):
    """Render one job template file into the output repo (executable)."""
    report = check_report if check_report is not None else GenerationCheckReport()
    preflight_generation(config, check_report=report)
    destination = check_relative_path(output_repo_base, output_relative_path,
                                      stage="job.preflight", report=report)
    check_output_path(destination, stage="job.preflight", report=report)
    for name, helper in RESOURCE_TEMPLATE_HELPERS.items():
        env.globals.setdefault(name, helper)
    source = _template_file(env, relative_path.as_posix())
    if source is not None:
        _job_input_guard([destination], report)(source)
    layers = ()
    if isinstance(env.loader, FileSystemLoader):
        layers = tuple((Path(root).absolute().name, Path(root)) for root in reversed(env.loader.searchpath))
    _render_single_job_file(relative_path, output_repo_base, output_relative_path, config, env, report,
                            source_layers=layers)


def _render_single_job_file(
    relative_path: Path, output_repo_base: str, output_relative_path: Path,
    config: "BaseWorkflowConfig", env: Environment, report: GenerationCheckReport,
    *, template_context: Mapping | None = None, file_mode: int | None = None,
    source_layers: tuple[tuple[str, Path], ...] = (),
) -> None:
    base_name = output_relative_path.stem
    if file_mode is not None and config.workflow_mode == "shell":
        from takflow._files import make_parents
        make_parents(Path(output_repo_base) / "logs/.log", Path(output_repo_base))
    output_log_dict = generate_output_log_data(
        config=config,
        name=base_name,
        output_repo_base=output_repo_base,
    )

    build_info_lines = _current_build_info_lines()
    data = {
        **(template_context or {}),
        "config": config,
        "build_info_warning": build_info_lines["warning"],
        "build_info_detail": build_info_lines["info"],
        **output_log_dict,
    }

    try:
        template = env.get_template(relative_path.as_posix())
        rendered_content = template.render(data)
        source = resource_source(Path(template.filename), source_layers) if template.filename else None
        rendered_content = job_source(rendered_content, source or f"template:{relative_path.as_posix()}",
                                      config.workflow_mode)
    except GenerationCheckError:
        raise
    except (TemplateError, TypeError, ValueError, OSError) as error:
        subject, reason = template_failure(relative_path, env, error)
        if file_mode is not None:
            report.failed("GEN_JOB_RENDER", "job.render", subject, reason)
            raise
        report.fail("GEN_JOB_RENDER", "job.render", subject, reason)

    output_file_path = Path(output_repo_base, output_relative_path)
    try:
        if file_mode is not None:
            from takflow._files import write_text
            write_text(output_file_path, rendered_content, file_mode, Path(output_repo_base))
            report.artifact(output_file_path, "job", stage="job.output")
            return
        output_file_path.parent.mkdir(exist_ok=True, parents=True)
        with open(output_file_path, "w") as f:
            f.write(rendered_content)
        mode = os.stat(output_file_path).st_mode
        os.chmod(output_file_path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError as error:
        reason = io_failure_reason("job output could not be written or its permissions could not be set", error)
        if file_mode is not None:
            report.failed("GEN_JOB_WRITE", "job.output", output_relative_path.as_posix(), reason)
            raise
        report.fail("GEN_JOB_WRITE", "job.output", output_relative_path.as_posix(), reason)
    report.artifact(output_file_path, "job", stage="job.output")


def generate_output_log_data(
    config: "BaseWorkflowConfig", name: str, output_repo_base: str
) -> Dict[str, str]:
    """Compute stdout/stderr log path template data for a job by mode/workload."""
    if config.workflow_mode == "ecflow":
        output = "%ECF_JOBOUT%"
        error = "%ECF_JOBOUT%.err"
    elif config.workflow_mode == "takler":
        output = "{{ TAKLER_JOBOUT }}"
        error = "{{ TAKLER_JOBOUT }}.err"
    else:
        logs = Path(output_repo_base, "logs")
        logs.mkdir(parents=True, exist_ok=True)
        suffix = ".%j" if config.workload.workload_type == "slurm" else ""
        output = str(logs / f"{name}{suffix}.out")
        error = str(logs / f"{name}{suffix}.err")
    return {"output_std_log_path": output, "output_stderr_log_path": error}


__all__ = ["render_jobs_from_directory", "render_single_job_file", "generate_output_log_data"]
