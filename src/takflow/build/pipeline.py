"""Standard generation stages, invocation results and atomic success manifests.

Use inside ``Application.prepare``. Full and single-stage calls share exactly
the same stage implementations; generation never submits or runs business code.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
from collections.abc import Callable

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError, TemplateNotFound

from takflow._files import file_state, io_failure_reason, make_parents, write_text
from takflow.application import BuildContext, ResourceEntry
from takflow.checks import (
    GenerationCheckError, GenerationCheckReport, check_input_file,
    check_output_path, check_relative_path,
)
from takflow.checks.diagnostics import template_failure
from takflow.config import ConfigValidationError
from takflow.flow.backends.ecflow._job_paths import ecflow_task_templates
from takflow.flow.backends.ecflow.serializer.attributes import _native_variable_quotes
from takflow.flow.hook import _safe_hook_errors
from takflow.flow.generate import GenerationContext, generate_workflow
from takflow.jobs.headers import RESOURCE_TEMPLATE_HELPERS
from takflow.jobs.render import render_jobs_from_directory
from takflow.jobs.provenance import job_source, prepared_source, resource_source
from takflow.config.credentials import CredentialHookPoint, get_credential_registry, render_credential
from takflow.build.assets import _copy_resource_layers
from takflow.build.manifest import publish_manifest
from takflow.build.result import BuildArtifact, BuildError, BuildResult, STAGES
from takflow.build.runtime_config import render_runtime_config


class _BuildChecks(GenerationCheckReport):
    def __init__(self, context: BuildContext):
        super().__init__()
        self.sensitive = {str(context.paths.config_dir / "credential.sh")}
        self.sensitive.update(str(context.paths.output_root / item.output) for item in context.outputs if item.mode == 0o600)

    def passed(self, code, stage, object, reason):
        # A build records writes and generation failures, not optional check receipts.
        pass

    def unchecked(self, code, stage, object, reason):
        if "PARTIAL" in code:
            super().unchecked(code, stage, object, reason)

    def artifact(self, path, role, *, stage="generation.output"):
        if str(path) not in self.sensitive:
            return super().artifact(path, role, stage=stage)
        path = check_input_file(path, stage=stage, report=self)
        self.artifacts[:] = [item for item in self.artifacts if item["path"] != str(path)]
        self.artifacts.append({"path": str(path), "role": role, "mode": oct(stat.S_IMODE(path.stat().st_mode))})


class _ResourceLoader(FileSystemLoader):
    def __init__(self, roots, report):
        super().__init__([str(root) for root in reversed(roots)])
        self.roots = roots
        self.report = report
        self.inputs: set[Path] = set()

    def get_source(self, environment, template):
        for root in reversed(self.roots):
            candidate = root / template
            if os.path.lexists(candidate):
                check_relative_path(root, template, stage="template.input", report=self.report)
                check_input_file(candidate, stage="template.input", report=self.report)
                break
        source, filename, current = super().get_source(environment, template)
        path = Path(filename)
        self.inputs.add(path)
        return source, filename, current


class _Pipeline:
    def __init__(self, context, *, credential_file=None, before_save=None, after_save=None):
        self.context = context
        self.root = context.paths.output_root
        self.manifest = self.root / "generation_manifest.json"
        self.report = _BuildChecks(context)
        self.result = BuildResult(context.config.workflow_mode, self.root, context.paths.workflow_output, "stage")
        self.credential_file = Path(credential_file).absolute() if credential_file is not None else None
        self.before_save = before_save
        self.after_save = after_save
        self.template_sources = {}
        self.stage = "resource"
        self.targets = {
            self.manifest: "manifest", context.paths.config_file: "config",
            context.paths.config_dir / "credential.sh": "credential",
            context.paths.workflow_output: "workflow",
        }
        self.loader = _ResourceLoader([layer.root for layer in context.paths.resource_layers], self.report)
        self.source_layers = tuple((layer.name, layer.root) for layer in context.paths.resource_layers)
        self.environment = Environment(loader=self.loader, undefined=StrictUndefined,
                                       lstrip_blocks=True, trim_blocks=True, keep_trailing_newline=True)
        self.environment.globals.update(context.template_context())
        self.environment.globals.update(RESOURCE_TEMPLATE_HELPERS, include_machine=self.include_machine)
        self.variables = {"OUTPUT_REPO_BASE": str(self.root), **context.variables}

    def fail(self, code, subject, reason):
        self.report.fail(code, self.stage, str(subject), reason)

    def reserve(self, path, role):
        path = Path(path)
        if path.is_relative_to(self.root):
            check_relative_path(self.root, path.relative_to(self.root), stage=self.stage, report=self.report)
        check_output_path(path, stage=self.stage, report=self.report)
        previous = self.targets.get(path)
        if previous is not None and previous != role:
            self.fail("BUILD_OUTPUT_COLLISION", path, "different artifact roles map to the same output")
        for other in self.targets:
            if other != path and (path.resolve() == other.resolve() or
                                  (path.exists() and other.exists() and path.samefile(other))):
                self.fail("BUILD_OUTPUT_COLLISION", path, "output paths alias the same physical file")
        self.targets[path] = role
        for source in self.loader.inputs | ({self.credential_file} if self.credential_file else set()):
            if path.resolve() == source.resolve() or (path.exists() and source.exists() and path.samefile(source)):
                self.fail("BUILD_INPUT_OUTPUT_OVERLAP", path, "output would overwrite a selected input")

    def record(self, path, role, *, kind="generated", mutable=False, source=None):
        path = Path(path)
        secret = str(path) in self.report.sensitive
        mode = oct(stat.S_IMODE(path.stat().st_mode)) if path.is_file() else None
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if mode and not secret else None
        previous = next((item for item in self.result.artifacts if item.path == str(path) and item.kind == kind), None)
        origins = list(previous.sources) if previous else []
        if source is not None and source not in origins:
            origins.append(source)
        artifact = BuildArtifact(str(path), role, self.stage, kind, mode, digest, mutable, secret, origins)
        if previous:
            self.result.artifacts.remove(previous)
        self.result.artifacts.append(artifact)

    def collect(self):
        """Collector failure must never replace a generation exception."""
        for item in self.report.artifacts:
            path = Path(item["path"])
            kind = "copied" if item["role"].startswith("resource") else "generated"
            old = next((value for value in self.result.artifacts if value.path == str(path) and value.kind == kind), None)
            source = None
            if "source" in item:
                source_path = Path(item["source"])
                self.loader.inputs.add(source_path)
                source = {"layer": item.get("layer") or "base", "path": str(source_path)}
            if (old is not None and old.mode == item["mode"] and old.sha256 == item.get("sha256")
                    and (source is None or source in old.sources)):
                continue
            mutable = self.context.machine is not None and path.is_relative_to(Path(str(self.context.machine.directory)))
            # Use the captured invocation bytes, not an unrelated directory scan.
            self.record(path, item["role"], kind=kind, mutable=mutable, source=source)

    def write(self, path, text, role, mode):
        self.reserve(path, role)
        before = file_state(path)
        completed = False
        try:
            write_text(path, text, mode, self.root)
            completed = True
        except OSError as error:
            self.report.failed("BUILD_OUTPUT_WRITE", self.stage + ".write", str(path),
                               io_failure_reason("could not write output or set its permissions", error))
            raise
        finally:
            try:
                if path.is_file() and (completed or file_state(path) != before):
                    self.record(path, role)
            except Exception:
                self.report.unchecked("BUILD_PARTIAL_UNREADABLE", self.stage, str(path),
                                      "partial output metadata could not be collected")

    def render(self, template, *, required=True):
        try:
            try:
                selected = self.environment.get_template(template)
            except TemplateNotFound as error:
                if not required and error.name == template:
                    return None
                raise
            self.template_sources[template] = selected.filename
            return selected.render(self.context.template_context())
        except GenerationCheckError:
            raise
        except (TemplateError, TypeError, ValueError, OSError) as error:
            subject, reason = template_failure(template, self.environment, error)
            self.report.failed("BUILD_TEMPLATE_RENDER", self.stage + ".render", subject, reason)
            raise

    def include_machine(self, relative):
        machine = self.context.machine
        if machine is None:
            self.fail("BUILD_MACHINE_DISABLED", "machine", "machine capability is not selected")
        path = PurePosixPath(relative)
        if not relative or path.is_absolute() or ".." in path.parts or path == PurePosixPath(".") or any(c in relative for c in ("\n", "\r", "\\", ">", "<")):
            self.fail("BUILD_MACHINE_REFERENCE", "machine", "machine fragment must be a safe relative POSIX path")
        target = machine.directory / path
        if self.context.config.workflow_mode == "ecflow" and any(char in str(target) for char in ("<", ">")):
            self.fail("BUILD_MACHINE_REFERENCE", "machine", "ecFlow include paths cannot contain angle delimiters")
        if machine.external:
            if not any(item.path == str(target) and item.kind == "reference" for item in self.result.artifacts):
                self.result.artifacts.append(BuildArtifact(str(target), "machine", self.stage, "reference", mutable=True))
        else:
            local = check_relative_path(self.root, target.relative_to(PurePosixPath(str(self.root))), stage=self.stage, report=self.report)
            check_input_file(local, stage=self.stage, report=self.report)
            self.record(local, "machine", kind="reference", mutable=True)
        if self.context.config.workflow_mode == "ecflow":
            if any(char.isspace() for char in relative):
                self.fail("BUILD_MACHINE_REFERENCE", "machine", "ecFlow fragment names cannot contain whitespace")
            # ecFlow tokenizes a literal include path before expanding variables.
            # Use a raw native path channel when the selected directory has spaces;
            # MACHINE_DIR remains shell-encoded for config exports.
            if " " in str(machine.directory):
                return f"%includenopp <%TAKFLOW_MACHINE_INCLUDE_DIR%/{relative}>"
            return f"%includenopp <{target}>"
        return '. "${MACHINE_DIR}"/' + shlex.quote(path.as_posix())

    def _resource_entries(self):
        entries = list(self.context.application.resource_entries)
        machine = self.context.machine
        if machine is not None and not machine.external:
            relative = f"machine/{machine.name}"
            entries.append(ResourceEntry(relative, relative, required=True))
        return [entry for entry in entries if self.context.components.keep_resource(entry.source)]

    def resource(self):
        for layer in self.context.paths.resource_layers:
            for relative in layer.required_inputs:
                path = check_relative_path(layer.root, relative, stage="resource.input", report=self.report)
                check_input_file(path, stage="resource.input", report=self.report)
        required = self.context.application.required_resource_inputs
        if callable(required):
            required = required(self.context.config)
        for relative in required:
            candidates = [check_relative_path(layer.root, relative, stage="resource.input", report=self.report)
                          for layer in self.context.paths.resource_layers]
            if not any(path.is_file() for path in candidates):
                self.fail("BUILD_RESOURCE_INPUT_REQUIRED", relative, "required input is absent from all source layers")
        if any(PurePosixPath(item.destination).parts[0] == "machine" for item in self.context.application.resource_entries):
            self.fail("BUILD_MACHINE_MAPPING", "resource_entries", "machine copying is managed by the common selection")
        machine = self.context.machine
        entries = self._resource_entries()
        for entry in entries:
            if entry.required and not any((layer.root / entry.source).exists() for layer in self.context.paths.resource_layers):
                self.fail("BUILD_RESOURCE_REQUIRED", entry.source, "required resource is absent from all layers")
        if machine is not None and not machine.external:
            for fragment in self.context.required_machine_fragments:
                if not any((layer.root / "machine" / machine.name / fragment).is_file()
                           for layer in self.context.paths.resource_layers):
                    self.fail("BUILD_MACHINE_FRAGMENT_REQUIRED", fragment, "required machine fragment is absent from all source layers")
        layers = []
        for layer in self.context.paths.resource_layers:
            mappings = [(entry.source, entry.destination, entry.executable) for entry in entries
                        if os.path.lexists(layer.root / entry.source)]
            layers.append((layer.name, layer.root, mappings))
        _copy_resource_layers(self.root, layers, keep=self.context.components.keep_resource,
                              check_report=self.report, check_target=lambda path: self.reserve(path, "resource"),
                              after_layer=self.collect)

        for fragment in self.context.required_machine_fragments:
            # Business scripts can source a fragment later in their own cwd
            # and Shell scope; validate/record it without moving that source.
            self.include_machine(fragment)

    def config(self):
        render_runtime_config(self, self.result.stages[STAGES.index("config")].skipped_outputs)

    def credential(self):
        enabled = self.context.application.credential_enabled
        if callable(enabled):
            enabled = enabled(self.context.config)
        if not enabled:
            if self.credential_file is not None:
                self.fail("BUILD_CREDENTIAL_DISABLED", "credential_file", "credential capability is disabled")
            return "credential capability disabled"
        if self.credential_file is None:
            self.fail("BUILD_CREDENTIAL_UNCONFIGURED", "credential_file", "enabled credentials require an explicit input file")
        check_input_file(self.credential_file, stage="credential.input", report=self.report)
        if not get_credential_registry().count_hooks(CredentialHookPoint.RENDER):
            self.fail("BUILD_CREDENTIAL_HOOK_REQUIRED", "credential", "enabled credentials require a registered contribution")
        path = self.context.paths.config_dir / "credential.sh"
        self.reserve(path, "credential")
        before = file_state(path)
        try:
            render_credential(str(self.credential_file), self.context.config, str(self.root), dict(self.context.build_info),
                              environment=self.environment, source_layers=self.source_layers)
        except (ConfigValidationError, GenerationCheckError):
            raise
        except Exception as error:
            self.report.failed("BUILD_CREDENTIAL_RENDER", "credential.render", str(path),
                               io_failure_reason("could not render or write the credential output", error))
            raise
        finally:
            try:
                if path.is_file() and file_state(path) != before:
                    self.record(path, "credential")
            except Exception:
                self.report.unchecked("BUILD_PARTIAL_UNREADABLE", "credential", str(path), "credential metadata could not be collected")

    def check_script_input(self, relative):
        if self.result.scope != "full":
            return
        path = str(check_relative_path(self.root, relative, stage="job.input", report=self.report))
        # Only writes from this invocation may satisfy a full build. The report
        # also contains jobs completed earlier in the current rendering call.
        prepared = any(item.path == path and item.kind != "reference" for item in self.result.artifacts)
        prepared = prepared or any(item["path"] == path for item in self.report.artifacts)
        if not prepared:
            self.fail("BUILD_SCRIPT_INPUT_NOT_PREPARED", relative,
                      "local script was not copied or generated by this full build")

    def config_inputs(self):
        stage = f"{self.stage}.input"
        check_input_file(self.context.paths.config_file, stage=stage, report=self.report)
        for output in self.context.outputs:
            if output.required:
                check_input_file(self.root / output.output, stage=stage, report=self.report)

    def job(self):
        self.config_inputs()
        sources = {item.path: item.sources[-1] for item in self.result.artifacts if item.sources}
        entries = tuple((item.source, item.destination) for item in self._resource_entries())

        def script_source(path, content):
            origin = sources.get(str(path), {})
            filename = origin.get("path") or origin.get("template")
            if filename:
                layers = self.source_layers
                if "layer" in origin:
                    layers = tuple(layer for layer in layers if layer[0] == origin["layer"])
                source = resource_source(Path(filename), layers)
                if source:
                    return source
            return prepared_source(path, content, self.source_layers, self.root, entries)

        planned = []
        before = {}

        def prepare_outputs(files):
            planned.extend(files)
            self.loader.inputs.update(source for source, _ in files)
            for _, target in files:
                self.reserve(target, "job")
                before[target] = file_state(target)
        try:
            render_jobs_from_directory(self.context.config, [layer.root for layer in self.context.paths.resource_layers],
                                       str(self.root), template_filter=self.context.components.keep_job,
                                       check_report=self.report, environment=self.environment,
                                       template_context=self.context.template_context(), file_mode=0o755, verbose=False,
                                       script_input_check=self.check_script_input, prepare_outputs=prepare_outputs,
                                       source_layers=self.source_layers, script_source=script_source)
        finally:
            for _, path in planned:
                try:
                    if path.is_file() and file_state(path) != before[path]:
                        self.record(path, "job")
                except Exception:
                    self.report.unchecked("BUILD_PARTIAL_UNREADABLE", "job", str(path), "job metadata could not be collected")
        for source, path in planned:
            self.record(path, "job", source={"template": str(source)})

    def workflow(self):
        self.config_inputs()
        path = self.context.paths.workflow_output
        self.reserve(path, "workflow")
        make_parents(path, self.root)

        def before_save(context: GenerationContext):
            # The engine carries shell-literal values so substitution into the
            # exported config cannot introduce command syntax. Domain variables
            # outside this explicit channel retain their existing semantics.
            context.suite.add_variables({name: shlex.quote(value) for name, value in self.variables.items()})
            machine = self.context.machine
            if self.context.config.workflow_mode == "ecflow" and machine and " " in str(machine.directory):
                if "TAKFLOW_MACHINE_INCLUDE_DIR" in self.variables:
                    self.fail("BUILD_VARIABLE_CONFLICT", "TAKFLOW_MACHINE_INCLUDE_DIR", "native machine path channel is reserved")
                context.suite.add_variable("TAKFLOW_MACHINE_INCLUDE_DIR", str(machine.directory))
            if self.before_save is not None:
                self.before_save(context)

            if self.result.mode == "ecflow":
                current_jobs = {Path(item.path) for item in self.result.artifacts if item.role == "job"}
                for node, candidates in ecflow_task_templates(context.suite):
                    if not candidates or not all(p.is_relative_to(self.context.paths.jobs_dir) for p in candidates):
                        continue
                    if self.result.scope == "full":
                        present = any(p in current_jobs for p in candidates)
                    else:
                        present = any(p.is_file() for p in candidates)
                    if not present:
                        self.fail("BUILD_JOB_INPUT_REQUIRED", node.path,
                                  f"enabled task requires a prepared job template: {candidates[-1]}")

        def shell_renderer(config, output_root, resource_root):
            template = self.context.application.shell_template
            text = self.render(template)
            filename = self.template_sources[template]
            source = resource_source(Path(filename), self.source_layers) or f"template:{template}"
            text = job_source(text, source, config.workflow_mode)
            self.write(path, text, "workflow", 0o755)
            self.record(path, "workflow", source={"template": filename})
            return path

        suite_builder = self.context.application.suite_builder
        if self.context.application.context_suite_builder is not None:
            def suite_builder(config, engine):
                return self.context.application.context_suite_builder(self.context, engine)

        before = file_state(path)
        quote_token = _native_variable_quotes.set(True)
        try:
            self.result.generation = generate_workflow(
                self.context.config, output=path, suite_builder=suite_builder,
                shell_renderer=shell_renderer, before_save=before_save, after_save=self.after_save,
                required_operations=self.context.application.required_operations(self.context.config) if self.context.application.required_operations else (),
                check_report=self.report,
            )
            path.chmod(0o755 if self.context.config.workflow_mode == "shell" else 0o644)
        finally:
            _native_variable_quotes.reset(quote_token)
            try:
                if path.is_file() and file_state(path) != before:
                    self.record(path, "shell_runner" if self.context.config.workflow_mode == "shell" else "definition")
            except Exception:
                self.report.unchecked("BUILD_PARTIAL_UNREADABLE", "workflow", str(path), "workflow metadata could not be collected")

    def run(self, stages, *, full):
        self.result.scope = "full" if full else "stage"
        self.stage = stages[0]
        token = _safe_hook_errors.set(True)
        try:
            if self.context.paths.workflow_output in {self.manifest, self.context.paths.config_file,
                                                     self.context.paths.config_dir / "credential.sh"}:
                self.fail("BUILD_OUTPUT_COLLISION", "workflow_output", "workflow output collides with a reserved artifact")
            if self.variables["OUTPUT_REPO_BASE"] != str(self.root):
                self.fail("BUILD_VARIABLE_CONFLICT", "OUTPUT_REPO_BASE", "output variable must match the effective output root")
            # Invalidate before the first mutating stage, including step calls.
            if any(name in stages for name in STAGES[:5]):
                try:
                    self.manifest.unlink(missing_ok=True)
                except OSError as error:
                    self.report.failed("BUILD_MANIFEST_INVALIDATE", "manifest.invalidate", str(self.manifest),
                                       io_failure_reason("could not invalidate the previous success manifest", error))
                    raise
            for name in stages:
                self.stage = name
                outcome = self.result.stages[STAGES.index(name)]
                reason = getattr(self, name)() if name != "report" else None
                outcome.status = "skipped" if reason else "passed"
                outcome.reason = reason
                self.collect()
            if full:
                self.stage = "report"
                try:
                    publish_manifest(self.context, self.result, self.manifest)
                except Exception as error:
                    self.report.failed("BUILD_MANIFEST_PUBLISH", "report.publish", str(self.manifest),
                                       io_failure_reason("could not publish the success manifest", error))
                    raise
        except Exception as error:
            outcome = self.result.stages[STAGES.index(self.stage)]
            outcome.status = "failed"
            outcome.reason = "generation failed; original exception and partial files retained"
            try:
                self.collect()
            except Exception:
                self.report.unchecked("BUILD_PARTIAL_UNREADABLE", self.stage, "artifacts", "partial artifact collection failed")
            self.result.diagnostics = []
            if isinstance(error, ConfigValidationError):
                self.result.diagnostics.extend(item.as_dict() for item in error.diagnostics)
                if self.stage == "credential":
                    for item in self.result.diagnostics:
                        if not item["path"]:
                            item["object"] = "credential_file"
            if isinstance(error, GenerationCheckError) and error.report is not self.report:
                self.result.diagnostics.append(asdict(error.diagnostic))
            self.report.failed("BUILD_STAGE_FAILED", self.stage, self.stage, "generation stage failed; original exception retained")
            self.result.diagnostics.extend(asdict(item) for item in self.report.checks)
            raise BuildError(self.result, error) from error
        finally:
            _safe_hook_errors.reset(token)
        return self.result


def build(context: BuildContext, *, credential_file=None, before_save: Callable | None = None,
          after_save: Callable | None = None) -> BuildResult:
    """Run all standard stages; publish the manifest after all generation stages succeed."""
    return _Pipeline(context, credential_file=credential_file, before_save=before_save, after_save=after_save).run(STAGES, full=True)


def run_stage(context: BuildContext, stage: str, *, credential_file=None,
              before_save: Callable | None = None, after_save: Callable | None = None) -> BuildResult:
    """Run one shared stage, with the same prerequisites; never publish success.

    Reports include only this invocation's writes. Existing prerequisite files
    may be checked, but are not adopted as newly generated artifacts.
    """
    if stage not in STAGES:
        raise ValueError(f"Unknown generation stage: {stage}")
    return _Pipeline(context, credential_file=credential_file, before_save=before_save, after_save=after_save).run((stage,), full=False)
