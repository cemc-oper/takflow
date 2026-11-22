"""Explicit application CLI over the public preparation and build lifecycle."""
from __future__ import annotations

from collections import Counter
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
from takflow.config.workload import RESOURCE_ALIAS_HINTS, ResourceAliasWarning


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


def _warning_diagnostics(captured):
    # Match the framework category and its fixed notices. Application text is private.
    counts = Counter(item.message.args[0] for item in captured
                     if type(item.message) is ResourceAliasWarning and len(item.message.args) == 1
                     and type(item.message.args[0]) is str)
    diagnostics = []
    suppressed = len(captured)
    for field, hint in RESOURCE_ALIAS_HINTS.items():
        count = counts[hint]
        if count:
            stage = "config.validation" if field == "workload.wckey" else "resource.render"
            diagnostics.append(_diagnostic("RESOURCE_ALIAS_DEPRECATED", hint, stage)
                               | {"object": field, "count": count})
            suppressed -= count
    if suppressed:
        diagnostics.append(_diagnostic("CLI_APPLICATION_WARNINGS", "application warnings suppressed")
                           | {"count": suppressed})
    return diagnostics


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
            for item in diagnostics:
                if item["stage"] == "config.read":
                    item["object"] = "--config-file"
            exit_code = 1
        except GenerationCheckError as error:
            diagnostics = [asdict(error.diagnostic)]
            exit_code = 1
        except KeyboardInterrupt:
            diagnostics = [_diagnostic("CLI_INTERRUPTED", "generation interrupted")]
            exit_code = 130
        except (Exception, SystemExit):
            code, subject, reason = {
                "application": ("CLI_APPLICATION_LOAD", "application", "could not import or initialize the application"),
                "prepare": ("CLI_PREPARE_FAILED", "application context", "could not prepare the generation context"),
                "build": ("CLI_BUILD_FAILED", options["stage"] or "build", "could not run the requested generation"),
            }[phase]
            diagnostics = [_diagnostic(code, reason, phase) | {"object": subject}]
            exit_code = 1
        finally:
            logging.disable(old_disable)
    return exit_code, {
        "schema_version": 1, "status": "failed" if exit_code else "success",
        "result": result.as_dict() if result is not None else None,
        "diagnostics": diagnostics,
        "warnings": _warning_diagnostics(captured),
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
        subject = diagnostic.get("object")
        if subject is None and "path" in diagnostic:
            subject = ".".join(map(str, diagnostic["path"])) or "$"
        location = f" {subject}" if subject is not None else ""
        click.echo(f"[{diagnostic['code']}] {diagnostic['stage']}{location}: {diagnostic['reason']}{count}")


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

    @cli.command("check")
    @click.option("--manifest", type=click.Path(path_type=str), help="Build inventory used for expansion or integrity.")
    @click.option("--definition", type=click.Path(path_type=str), help="Generated definition, defaults to the manifest entry.")
    @click.option("--mode", type=click.Choice(["ecflow", "takler"]), help="Definition format if it cannot be inferred.")
    @click.option("--parse-definition", "parse", is_flag=True, help="Only read and parse the definition.")
    @click.option("--expand", multiple=True, metavar="TASK", help="Preprocess a selected absolute task path in a temporary directory.")
    @click.option("--shell", multiple=True, type=click.Path(path_type=str), help="Check a concrete script with its declared shell.")
    @click.option("--integrity", is_flag=True, help="Compare recorded files and permissions with the build inventory.")
    @click.pass_context
    def check(context, **options):
        """Check selected artifacts without loading an application."""
        from takflow.artifact_checks import check_artifacts
        if not any(options[key] for key in ("parse", "expand", "shell", "integrity")):
            raise click.UsageError("select --parse-definition, --expand, --shell or --integrity")
        result = check_artifacts(**options)
        if context.obj["format"] == "json":
            click.echo(json.dumps(result.as_dict(), ensure_ascii=True))
        else:
            for item in result.checks:
                click.echo(f"{item['scope']} {item['object']}: {item['status']} ({item['reason']})")
        context.exit(0 if result.passed else 1)

    cli.command("build", help="Run the complete standard generation pipeline.")(command(None))
    for stage in ("resource", "config", "credential", "job", "workflow"):
        group = click.Group(stage, help=f"Run only the {stage} stage.", no_args_is_help=False)
        group.command("copy" if stage == "resource" else "generate")(command(stage))
        cli.add_command(group)
    return cli


main = create_cli()

__all__ = ["create_cli", "load_application", "ApplicationLoadError", "main"]
