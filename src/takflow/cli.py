"""Explicit application CLI over the public preparation and build lifecycle."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
import importlib
import json
import logging
import os
import re
import warnings
from typing import Callable

import click

from takflow import __version__
from takflow.application import Application
from takflow.build import BuildError, build, run_stage
from takflow.checks import GenerationCheckError
from takflow.config import ConfigValidationError


class ApplicationLoadError(ValueError):
    """Controlled import/factory failure; the Python caller retains the cause."""


def load_application(reference: str) -> Application:
    """Resolve an explicit ``module:attribute`` instance or zero-argument factory."""
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*", reference):
        raise ApplicationLoadError("application must be an explicit module:attribute reference")
    try:
        module, attribute = reference.split(":")
        value = getattr(importlib.import_module(module), attribute)
        value = value if isinstance(value, Application) else value()
        if not isinstance(value, Application):
            raise TypeError("application factory must return Application")
        return value
    except (Exception, SystemExit) as error:
        raise ApplicationLoadError("application could not be loaded") from error


def _diagnostic(code, reason, stage="cli"):
    return {"code": code, "stage": stage, "reason": reason}


def _execute(application, options):
    """Suppress arbitrary application text while retaining safe service reports."""
    result = None
    diagnostics = []
    exit_code = 0
    phase = "application"
    old_disable = logging.root.manager.disable
    with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink), warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        logging.disable(logging.CRITICAL)
        try:
            if isinstance(application, str):
                application = load_application(application)
            elif not isinstance(application, Application):
                application = application()
            if not isinstance(application, Application):
                raise ApplicationLoadError("application factory must return Application")
            phase = "prepare"
            overrides = {key: options[key] for key in ("machine_name", "machine_dir") if options[key] is not None}
            with application.prepare(
                options["config_file"], overrides=overrides,
                output_repo_base=options["output_repo_base"],
                workflow_repo_base=options["workflow_repo_base"], output=options.get("output"),
            ) as context:
                phase = "build"
                arguments = {"credential_file": options.get("credential_file")}
                result = (build(context, **arguments) if options["stage"] is None else
                          run_stage(context, options["stage"], **arguments))
        except BuildError as error:
            result = error.result
            exit_code = 1
        except ConfigValidationError as error:
            diagnostics = [item.as_dict() for item in error.diagnostics]
            exit_code = 1
        except GenerationCheckError as error:
            diagnostics = [asdict(error.diagnostic)]
            exit_code = 1
        except KeyboardInterrupt:
            diagnostics = [_diagnostic("CLI_INTERRUPTED", "generation interrupted")]
            exit_code = 130
        except (Exception, SystemExit):
            code = "CLI_APPLICATION_LOAD" if phase == "application" else "CLI_PREPARE_FAILED" if phase == "prepare" else "CLI_BUILD_FAILED"
            diagnostics = [_diagnostic(code, "application loading failed" if phase == "application" else "generation preparation or execution failed", phase)]
            exit_code = 1
        finally:
            logging.disable(old_disable)
    return exit_code, {
        "schema_version": 1, "status": "failed" if exit_code else "success",
        "result": result.as_dict() if result is not None else None,
        "diagnostics": diagnostics,
        "warnings": ([_diagnostic("CLI_APPLICATION_WARNINGS", "application warnings suppressed") | {"count": len(captured)}] if captured else []),
    }


def _display(report, format):
    if format == "json":
        click.echo(json.dumps(report, ensure_ascii=True))
        return
    click.echo(report["status"])
    result = report["result"]
    if result is not None:
        for stage in result["stages"]:
            click.echo(f"{stage['name']}: {stage['status']}" + (f" ({stage['reason']})" if stage["reason"] else ""))
            for path in stage["skipped_outputs"]:
                click.echo(f"  skipped output: {path}")
        for artifact in result["artifacts"]:
            click.echo(f"{artifact['role']} [{artifact['kind']} {artifact['mode'] or '-'}]: {artifact['path']}")
        if result["manifest_path"]:
            click.echo(f"manifest: {result['manifest_path']}")
    for diagnostic in report["diagnostics"] + (result["diagnostics"] if result else []) + report["warnings"]:
        count = f" ({diagnostic['count']})" if "count" in diagnostic else ""
        click.echo(f"[{diagnostic['code']}] {diagnostic['stage']}: {diagnostic['reason']}{count}")


def create_cli(application: Application | Callable[[], Application] | str | None = None, *, name: str = "takflow") -> click.Group:
    """Create the standard commands, optionally bound to one declared application.

    No application factory runs until a correctly parsed leaf command executes.
    Root options precede the command. See the standard CLI guide for the contract.
    """
    @click.group(name=name, no_args_is_help=False)
    @click.option("--format", type=click.Choice(["text", "json"]), default="text", show_default=True)
    @click.version_option(version=__version__, prog_name=name)
    @click.pass_context
    def cli(context, format, **values):
        """Generate workflows through an explicit Application declaration."""
        context.ensure_object(dict)
        context.obj.update(format=format, application=application or values.get("application"))

    if application is None:
        cli = click.option("--application", help="Explicit module:attribute Application or no-argument factory.")(cli)

    def command(stage):
        @click.pass_context
        def invoke(context, **options):
            selected = context.obj["application"]
            if selected is None:
                raise click.UsageError("--application module:attribute is required", context)
            code, report = _execute(selected, {**options, "stage": stage})
            _display(report, context.obj["format"])
            context.exit(code)

        for flag, help_text in (
            ("machine-dir", "Absolute target machine directory (not probed locally)."),
            ("machine-name", "Machine selection before configuration validation."),
            ("workflow-repo-base", "Override the application resources root."),
            ("output-repo-base", "Override the output root, relative to the working directory."),
            ("config-file", "Application YAML configuration file."),
        ):
            invoke = click.option("--" + flag, required=flag == "config-file", help=help_text)(invoke)
        if stage in (None, "workflow"):
            invoke = click.option("--output", help="Explicit workflow output path.")(invoke)
        if stage in (None, "credential"):
            invoke = click.option("--credential-file", help="Credential input file; never credential content.")(invoke)
        return invoke

    cli.command("build", help="Run the complete standard generation pipeline.")(command(None))
    for stage in ("resource", "config", "credential", "job", "workflow"):
        group = click.Group(stage, help=f"Run only the {stage} stage.", no_args_is_help=False)
        group.command("copy" if stage == "resource" else "generate")(command(stage))
        cli.add_command(group)
    return cli


main = create_cli()

__all__ = ["create_cli", "load_application", "ApplicationLoadError", "main"]
