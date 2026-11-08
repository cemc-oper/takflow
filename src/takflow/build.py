"""Standard generation stages, invocation results and atomic success manifests.

Use inside ``Application.prepare``. Full and single-stage calls share exactly
the same stage implementations; generation never submits or runs business code.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import shlex
import stat
import tempfile
from typing import Any, Callable
from uuid import uuid4

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from takflow import __version__
from takflow._files import file_state, make_parents, write_text
from takflow.application import BuildContext, ResourceEntry
from takflow.backends.ecflow.serializer.attributes import _native_variable_quotes
from takflow.checks import (
    GenerationCheckReport, check_input_file,
    check_output_path, check_relative_path, check_shell_output,
)
from takflow.config import ConfigValidationError
from takflow.flow.hook import _safe_hook_errors
from takflow.generation import GenerationContext, GenerationResult, generate_workflow
from takflow.spec.jobspec import contract_version
from takflow.toolkit.credential import CredentialHookPoint, get_credential_registry, render_credential
from takflow.toolkit.job import render_jobs_from_directory, render_orvix_resource_block
from takflow.toolkit.resource import copy_resource_entries


STAGES = ("resource", "config", "credential", "job", "workflow", "check", "report")


@dataclass
class StageResult:
    name: str
    status: str = "not_run"
    reason: str | None = None
    skipped_outputs: list[str] = field(default_factory=list)


@dataclass
class BuildArtifact:
    path: str
    role: str
    stage: str
    kind: str = "generated"
    mode: str | None = None
    sha256: str | None = None
    mutable: bool = False
    sensitive: bool = False
    sources: list[dict[str, str]] = field(default_factory=list)


@dataclass
class BuildResult:
    mode: str
    output_root: Path
    workflow_output: Path
    scope: str
    build_id: str = field(default_factory=lambda: uuid4().hex)
    complete: bool = False
    manifest_path: Path | None = None
    stages: list[StageResult] = field(default_factory=lambda: [StageResult(name) for name in STAGES])
    artifacts: list[BuildArtifact] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    generation: GenerationResult | None = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        """A controlled report: no raw config, credential data or exception text."""
        return {
            "build_id": self.build_id, "scope": self.scope, "complete": self.complete,
            "mode": self.mode, "output_root": str(self.output_root),
            "workflow_output": str(self.workflow_output),
            "manifest_path": str(self.manifest_path) if self.manifest_path else None,
            "stages": [asdict(value) for value in self.stages],
            "artifacts": [{key: value for key, value in asdict(item).items()
                           if not (item.sensitive and key == "sha256")} for item in self.artifacts],
            "diagnostics": list(self.diagnostics),
        }


class BuildError(RuntimeError):
    """Safe message with a partial result and the unchanged original exception."""

    def __init__(self, result: BuildResult, original: Exception):
        self.result = result
        self.original = original
        stage = next((item.name for item in result.stages if item.status == "failed"), "build")
        super().__init__(f"[BUILD_FAILED] {stage}: generation failed; partial result and original exception retained")


class _BuildChecks(GenerationCheckReport):
    def __init__(self, context: BuildContext):
        super().__init__(checks=list(context.checks.checks))
        self.sensitive = {str(context.paths.config_dir / "credential.sh")}
        self.sensitive.update(str(context.paths.output_root / item.output) for item in context.outputs if item.mode == 0o600)

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
            if candidate.is_file():
                check_relative_path(root, template, stage="template.input", report=self.report)
                check_input_file(candidate, stage="template.input", report=self.report)
                break
        source, filename, current = super().get_source(environment, template)
        path = Path(filename)
        root = next(root for root in self.roots if path.is_relative_to(root))
        check_relative_path(root, path.relative_to(root), stage="template.input", report=self.report)
        check_input_file(path, stage="template.input", report=self.report)
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
        self.environment = Environment(loader=self.loader, undefined=StrictUndefined,
                                       lstrip_blocks=True, trim_blocks=True, keep_trailing_newline=True)
        self.environment.globals.update(context.template_context())
        self.environment.globals.update(include_machine=self.include_machine,
                                        render_orvix_resource_block=render_orvix_resource_block)
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
        finally:
            try:
                if path.is_file() and (completed or file_state(path) != before):
                    self.record(path, role)
            except Exception:
                self.report.unchecked("BUILD_PARTIAL_UNREADABLE", self.stage, str(path),
                                      "partial output metadata could not be collected")

    def render(self, template):
        selected = self.environment.get_template(template)
        self.template_sources[template] = selected.filename
        return selected.render(self.context.template_context())

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
            self.report.unchecked("BUILD_EXTERNAL_MACHINE_UNCHECKED", self.stage, str(target),
                                  "external target fragment is not probed on the generation host")
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

    def resource(self):
        required = self.context.application.required_resource_inputs
        if callable(required):
            required = required(self.context.config)
        for relative in required:
            candidates = [check_relative_path(layer.root, relative, stage="resource.input", report=self.report)
                          for layer in self.context.paths.resource_layers]
            if not any(path.is_file() for path in candidates):
                self.fail("BUILD_RESOURCE_INPUT_REQUIRED", relative, "required input is absent from all source layers")
        entries = list(self.context.application.resource_entries)
        if any(PurePosixPath(item.destination).parts[0] == "machine" for item in entries):
            self.fail("BUILD_MACHINE_MAPPING", "resource_entries", "machine copying is managed by the common selection")
        machine = self.context.machine
        if machine is not None and not machine.external:
            relative = f"machine/{machine.name}"
            entries.append(ResourceEntry(relative, relative, required=True))
        entries = [entry for entry in entries if self.context.components.keep_resource(entry.source)]
        for entry in entries:
            if entry.required and not any((layer.root / entry.source).exists() for layer in self.context.paths.resource_layers):
                self.fail("BUILD_RESOURCE_REQUIRED", entry.source, "required resource is absent from all layers")
        if machine is not None and not machine.external:
            for fragment in self.context.application.required_machine_fragments:
                if not any((layer.root / "machine" / machine.name / fragment).is_file()
                           for layer in self.context.paths.resource_layers):
                    self.fail("BUILD_MACHINE_FRAGMENT_REQUIRED", fragment, "required machine fragment is absent from all source layers")
        for layer in self.context.paths.resource_layers:
            mappings = [(entry.source, entry.destination, entry.executable) for entry in entries
                        if (layer.root / entry.source).exists() and self.context.components.keep_resource(entry.source)]
            copy_resource_entries(self.root, layer.root, mappings, keep=self.context.components.keep_resource,
                                  check_report=self.report, check_target=lambda path: self.reserve(path, "resource"),
                                  source_layer=layer.name)
            self.collect()

        for fragment in self.context.application.required_machine_fragments:
            # Business scripts can source a fragment later in their own cwd
            # and Shell scope; validate/record it without moving that source.
            self.include_machine(fragment)

    def config(self):
        context = self.context
        planned = [(context.application.config_template, context.paths.config_file, "config", 0o644, True)]
        planned.extend((item.template, self.root / item.output, "extra", item.mode, item.required) for item in context.outputs)
        seen = set()
        for _, path, role, _, _ in planned:
            if path in seen:
                self.fail("BUILD_OUTPUT_COLLISION", path, "multiple configured artifacts share a destination")
            seen.add(path)
            self.reserve(path, role)
        for template, path, role, mode, required in planned:
            try:
                text = self.render(template)
            except TemplateNotFound as error:
                if required or error.name != template:
                    raise
                self.result.stages[STAGES.index("config")].skipped_outputs.append(str(path))
                continue
            if role == "config":
                lines = []
                for name, value in self.variables.items():
                    encoded = (f"%{name}%" if context.config.workflow_mode == "ecflow"
                               else shlex.quote(value))
                    lines.append(f"export {name}={encoded}")
                text = "\n".join(lines) + "\n" + text
            self.write(path, text, role, mode)
            self.record(path, role, source={"template": self.template_sources[template]})
            if mode != 0o600:
                check_shell_output(path, check_report=self.report, stage="config.output", role=role)

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
                              environment=self.environment, file_mode=0o600)
        finally:
            try:
                if path.is_file() and file_state(path) != before:
                    self.record(path, "credential")
            except Exception:
                self.report.unchecked("BUILD_PARTIAL_UNREADABLE", "credential", str(path), "credential metadata could not be collected")
        check_shell_output(path, check_report=self.report, stage="credential.output", role="credential")

    def job_inputs(self):
        templates = {}
        for layer in self.context.paths.resource_layers:
            directory = layer.root / "jobs"
            if directory.is_dir():
                for path in sorted(directory.rglob("*.j2")):
                    relative = path.relative_to(directory)
                    if self.context.components.keep_job(relative):
                        templates[relative] = path
        suffix = ".ecf" if self.context.config.workflow_mode == "ecflow" else ".sh"
        return [(path, self.context.paths.jobs_dir / relative.parent / (relative.stem.removesuffix(".sh") + suffix))
                for relative, path in templates.items()]

    def job(self):
        check_input_file(self.context.paths.config_file, stage="job.input", report=self.report)
        planned = self.job_inputs()
        before = {}
        for source, target in planned:
            self.loader.inputs.add(source)
            self.reserve(target, "job")
            before[target] = file_state(target)
        try:
            render_jobs_from_directory(self.context.config, [layer.root for layer in self.context.paths.resource_layers],
                                       str(self.root), template_filter=self.context.components.keep_job,
                                       check_report=self.report, environment=self.environment,
                                       template_context=self.context.template_context(), file_mode=0o755, verbose=False)
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
        check_input_file(self.context.paths.config_file, stage="workflow.input", report=self.report)
        for _, path in self.job_inputs():
            check_input_file(path, stage="workflow.input", report=self.report, executable=True)
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

        def shell_renderer(config, output_root, resource_root):
            text = self.render(self.context.application.shell_template)
            self.write(path, text, "workflow", 0o755)
            self.record(path, "workflow", source={"template": self.template_sources[self.context.application.shell_template]})
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

    def check(self):
        for path in [self.context.paths.config_file, self.context.paths.workflow_output,
                     *(target for _, target in self.job_inputs())]:
            check_input_file(path, stage="build.check", report=self.report)
        for item in self.result.artifacts:
            if item.kind == "reference" and item.mode is None:
                continue
            path = check_input_file(item.path, stage="build.check", report=self.report)
            mode = oct(stat.S_IMODE(path.stat().st_mode))
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if not item.sensitive else None
            if item.mutable:
                if digest != item.sha256 or mode != item.mode:
                    self.report.unchecked("BUILD_MUTABLE_REFERENCE_CHANGED", "build.check", item.path,
                                          "machine fragment differs from its build-time observation; reference remains updateable")
            elif digest != item.sha256 or mode != item.mode:
                self.fail("BUILD_ARTIFACT_CHANGED", item.path, "registered artifact content or permissions changed during the build")
        self.report.passed("BUILD_ARTIFACTS_VALID", "build.check", "artifacts", "registered invocation artifacts checked; stale files not adopted")

    def publish(self):
        public_inputs = {"mode": self.result.mode, "workflow_name": self.context.config.workflow_name,
                         "script_invoke_mode": self.context.config.script_invoke_mode,
                         "components": sorted(self.context.components.enabled)}
        payload = self.result.as_dict()
        payload.update(schema_version=1, complete=True, manifest_path=str(self.manifest),
                       versions={"takflow": __version__, "python": platform.python_version(),
                                 "application": self.context.brand.version, "tool_name": self.context.brand.tool_name,
                                 "target_model": self.context.brand.target_model, "jobspec": contract_version()},
                       config_fingerprint={"scope": "public-generation-options", "sha256": hashlib.sha256(json.dumps(public_inputs, sort_keys=True).encode()).hexdigest()},
                       resource_layers=[{"name": layer.name, "root": str(layer.root)} for layer in self.context.paths.resource_layers])
        payload["implementation_sha256"] = {
            name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
            for name in ("application.py", "build.py", "generation.py", "checks.py", "_files.py", "flow/hook.py",
                         "toolkit/job.py", "toolkit/resource.py", "toolkit/credential.py", "backends/ecflow/serializer/attributes.py")
        }
        spec = Path(__file__).parent / "spec"
        payload["versions"]["orvix_pin"] = (spec / "jobspec/ORVIX_VERSION").read_text().strip()
        payload["versions"]["takler_pin"] = (spec / "takler/TAKLER_VERSION").read_text().strip()
        make_parents(self.manifest, self.root)
        descriptor, temporary = tempfile.mkstemp(prefix=".generation_manifest.", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                os.fchmod(stream.fileno(), 0o644)
                stream.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.manifest)
        finally:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
        self.result.manifest_path = self.manifest
        self.result.complete = True

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
                self.manifest.unlink(missing_ok=True)
            for name in stages:
                self.stage = name
                outcome = self.result.stages[STAGES.index(name)]
                reason = getattr(self, name)() if name != "report" else None
                outcome.status = "skipped" if reason else "passed"
                outcome.reason = reason
                self.collect()
            self.result.diagnostics = [asdict(item) for item in self.report.checks]
            if full:
                self.stage = "report"
                self.publish()
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
            self.report.failed("BUILD_STAGE_FAILED", self.stage, self.stage, "generation stage failed; original exception retained")
            self.result.diagnostics.extend(asdict(item) for item in self.report.checks)
            raise BuildError(self.result, error) from error
        finally:
            _safe_hook_errors.reset(token)
        return self.result


def build(context: BuildContext, *, credential_file=None, before_save: Callable | None = None,
          after_save: Callable | None = None) -> BuildResult:
    """Run all standard stages; publish success only after final checks pass."""
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


__all__ = ["build", "run_stage", "BuildResult", "StageResult", "BuildArtifact", "BuildError", "STAGES"]
