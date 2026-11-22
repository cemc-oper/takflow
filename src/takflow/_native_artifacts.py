"""Stage only recorded templates for native, offline creation of one selected job."""
from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys
import re
import shutil

from jinja2 import TemplateError, TemplateNotFound, TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

from takflow._job_paths import ecflow_templates
from takflow._files import io_failure_reason
from takflow.artifact_checks import InvalidArtifact, Unavailable


def _search(inventory, directories, name):
    relative = Path(name)
    if ".." in relative.parts:
        raise Unavailable("include path leaves its selected directory")
    if relative.is_absolute():
        return inventory.select([relative])
    for directory in directories:
        if not directory.is_relative_to(inventory.original):
            raise Unavailable("include search requires a directory outside the recorded outputs")
        candidate = directory / relative
        if candidate in inventory.files:
            return candidate
    raise Unavailable("include is outside the recorded outputs: " + name)


def _safe_task(name):
    if not re.fullmatch(r"(?:/[A-Za-z0-9_.-]+)+", name) or any(p in (".", "..") for p in name.split("/")):
        raise Unavailable("native expansion requires an absolute task path with literal components")


def _ecflow_variables(defs, task):
    variables = {v.name(): v.value() for v in defs.user_variables}
    lineage = []
    while task is not None:
        lineage.append(task)
        task = task.get_parent()
    for node in reversed(lineage):
        variables.update({v.name(): v.value() for v in node.variables})
    return variables


def expand_ecflow(defs, name, inventory, work):
    import ecflow

    _safe_task(name)
    task = defs.find_abs_node(name)
    if not isinstance(task, ecflow.Task):
        raise InvalidArtifact("selected task is absent from the definition")
    variables = _ecflow_variables(defs, task)
    if variables.get("ECF_MICRO", "%") != "%":
        raise Unavailable("cannot isolate a nonstandard ecFlow directive delimiter")
    if variables.get("ECF_FETCH") or variables.get("ECF_FETCH_CMD"):
        raise Unavailable("cannot isolate an ecFlow template-fetch command")
    candidates = ecflow_templates(name, variables)
    if not candidates:
        raise Unavailable("cannot statically locate the ecFlow template from ECF_SCRIPT_CMD or ECF_FILES")
    source = inventory.select(candidates)
    directories = [Path(p) for p in variables.get("ECF_INCLUDE", "").split(":") if p]
    if not directories and variables.get("ECF_HOME"):
        directories = [Path(variables["ECF_HOME"])]
    staged = {}
    inputs = work / "templates"
    inputs.mkdir()

    def substitute(match):
        variable, default = match.groups()
        if variable in variables:
            return variables[variable]
        if default is not None:
            return default
        raise Unavailable("cannot isolate include using unresolved variable " + variable)

    def stage(path, raw=False):
        key = (path, raw)
        if key in staged:
            return staged[key]
        target = inputs / ("part-" + str(len(staged)))
        staged[key] = target
        local = inventory.local(path)
        if raw:
            shutil.copyfile(local, target)
            return target
        result = []
        nopp = False
        for line in local.read_text(encoding="utf-8").splitlines(keepends=True):
            directive = line.strip()
            if nopp:
                result.append(line)
                if directive == "%end":
                    nopp = False
                continue
            if line.rstrip("\r\n") == "%nopp":
                nopp = True
            if directive.startswith("%include"):
                match = re.fullmatch(r'(%include(?:nopp|once)?)\s+<([^<>]+)>', directive)
                if match is None:
                    raise Unavailable("cannot isolate this ecFlow include form")
                kind, operand = match.groups()
                value = re.sub(r"%([A-Za-z_]\w*)(?::([^%]*))?%", substitute, operand)
                if "%" in value:
                    raise Unavailable("cannot resolve the ecFlow include path")
                other = stage(_search(inventory, directories, value), raw=kind == "%includenopp")
                line = f"{kind} <{other.name}>\n"
            elif directive.startswith("%ecfmicro"):
                raise Unavailable("cannot isolate an ecFlow directive delimiter change")
            result.append(line)
        target.write_text("".join(result), encoding="utf-8")
        return target

    # Keep native node variables/repeats but remove template-fetch commands at every inherited scope.
    script = stage(source)
    shutil.copyfile(script, inputs / (task.name() + ".ecf"))
    node = task
    while node is not None:
        for variable in list(node.variables):
            if variable.name() in ("ECF_SCRIPT_CMD", "ECF_FETCH", "ECF_FETCH_CMD"):
                node.delete_variable(variable.name())
        node = node.get_parent()
    for variable in list(defs.user_variables):
        if variable.name() in ("ECF_SCRIPT_CMD", "ECF_FETCH", "ECF_FETCH_CMD"):
            defs.delete_variable(variable.name())
    jobs = work / "jobs"
    jobs.mkdir()
    for key, value in {"ECF_FILES": inputs, "ECF_INCLUDE": inputs, "ECF_HOME": jobs, "ECF_OUT": jobs,
                       "ECF_JOB": jobs / "selected.job0", "ECF_EXTN": ".ecf"}.items():
        task.add_variable(key, str(value))
    control = ecflow.JobCreationCtrl()
    control.set_node_path(name)
    control.set_dir_for_job_creation(str(jobs))
    defs.check_job_creation(control)
    message = control.get_error_msg()
    if message:
        reason = ("ecFlow could not substitute a job variable" if "EcfFile::variableSubstitution: failed" in message
                  else "ecFlow rejected the isolated job template")
        raise InvalidArtifact(f"{reason} while expanding {inventory.local(source)}")
    found = list(jobs.rglob("*.job0"))
    if len(found) != 1:
        raise Unavailable("ecFlow did not create the selected job in the temporary directory")
    return found[0]


def expand_takler(definition, name, inventory, work):
    # The pinned renderer constructs its Jinja environment internally. Install a
    # confined loader in a fresh interpreter so concurrent users retain their own environment.
    args = [sys.executable, "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); from takflow._native_artifacts import _worker; _worker()",
            str(Path(__file__).resolve().parents[1])]
    request = [str(definition), name, str(inventory.path), str(work)]
    child = subprocess.run(args, input=json.dumps(request), text=True, capture_output=True)
    if child.returncode:
        raise Unavailable("isolated takler worker did not complete")
    try:
        status, message = json.loads(child.stdout)
    except ValueError as error:
        raise Unavailable("isolated takler worker returned no result") from error
    if status == "incomplete":
        raise Unavailable(message)
    if status != "passed":
        raise InvalidArtifact(message)
    return work / message


def _worker():
    from takflow.artifact_checks import Inventory, _parse
    definition, name, manifest, directory = json.load(sys.stdin)
    try:
        flow = _parse(Path(definition), "takler")
        job = _takler_job(flow, name, Inventory(manifest), Path(directory))
        response = ["passed", str(job.relative_to(directory))]
    except (ImportError, Unavailable) as error:
        response = ["incomplete", str(error) if isinstance(error, Unavailable) else "native takler is unavailable"]
    except InvalidArtifact as error:
        response = ["failed", str(error)]
    except UnicodeError:
        response = ["failed", "generated artifact is not valid UTF-8"]
    except OSError as error:
        response = ["incomplete", io_failure_reason("could not stage or access files for the takler check", error)]
    except (ValueError, RuntimeError):
        response = ["incomplete", "isolated takler check could not complete"]
    print(json.dumps(response))


def _takler_job(flow, name, inventory, work):
    from takler.exceptions import TaklerError
    from takler.tasks.shell import shell_render
    from takler.tasks.shell.shell_script_task import ShellScriptTask

    _safe_task(name)
    task = flow.find_node(name)
    if not isinstance(task, ShellScriptTask):
        raise Unavailable("selected node is not a native takler shell task")
    script_param = task.find_user_parameter("TAKLER_SCRIPT")
    source = (script_param.value if script_param else task.script_path)
    if not source or not Path(source).is_absolute():
        raise Unavailable("cannot isolate the task's TAKLER_SCRIPT")
    script = Path(source)
    include = task.find_parent_parameter("TAKLER_INCLUDE")
    directories = [Path(p) for p in str(include.value).split(":") if p] if include else []
    templates = work / "templates"
    script = inventory.select([script])
    local = inventory.local(script)
    if not script.is_relative_to(inventory.original):
        raise Unavailable("takler script is outside the selected output tree")
    source = templates / script.relative_to(inventory.original)
    source.parent.mkdir(parents=True)
    shutil.copyfile(local, source)
    search = [script.parent, *directories]

    class OutputLoader(shell_render._BoundedFileSystemLoader):
        def get_source(self, environment, template):
            # Let Jinja apply guards, include lists and ignore-missing at render time.
            from jinja2.loaders import split_template_path
            try:
                split_template_path(template)
            except TemplateNotFound as error:
                raise Unavailable("cannot isolate a takler include path") from error
            if Path(template).is_absolute():
                raise Unavailable("cannot isolate an absolute takler include")
            for directory in search:
                if not directory.is_relative_to(inventory.original) or ".." in directory.parts:
                    raise Unavailable("takler include search leaves the recorded outputs")
                original = directory / template
                if original in inventory.files:
                    selected = inventory.local(original)
                    staged = templates / original.relative_to(inventory.original)
                    if not staged.exists():
                        staged.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(selected, staged)
                    return super().get_source(environment, template)
            raise TemplateNotFound(template)

    shell_render.Environment = SandboxedEnvironment
    shell_render._BoundedFileSystemLoader = OutputLoader
    target = work / "jobs"
    flow.add_parameter("TAKLER_HOME", str(target))
    task.add_parameter("TAKLER_HOME", str(target))
    task.add_parameter("TAKLER_SCRIPT", str(source))
    task.add_parameter("TAKLER_INCLUDE", ":".join(str(templates / p.relative_to(inventory.original))
                                                  for p in directories if p.is_relative_to(inventory.original)))
    for key, suffix in (("TAKLER_JOB", "job"), ("TAKLER_JOBOUT", "out")):
        declared = task._artifact_override(key)
        if declared and (not isinstance(declared.value, str) or declared.value.count("{attempt_id}") != 1):
            raise Unavailable("cannot isolate the explicit " + key + " path")
        task.add_parameter(key, str(target / ("selected.{attempt_id}." + suffix)))
    task.add_parameter("TAKLER_SHELL_JOB_CMD", "true")
    try:
        flow.begin()
        task.increment_try_no()
        expected = target / ("selected." + task.attempt_id + ".job")
        if task._artifact_paths()[0] != expected or not expected.resolve().is_relative_to(work.resolve()):
            raise Unavailable("takler resolved the job outside the isolated destination")
        task.check_job_creation()
    except TaklerError as error:
        cause = error
        while cause is not None:
            if isinstance(cause, (Unavailable, InvalidArtifact)):
                raise cause
            if isinstance(cause, TemplateNotFound):
                raise Unavailable("required takler include is outside the recorded outputs") from error
            if isinstance(cause, OSError):
                raise Unavailable(io_failure_reason("could not access files for takler job creation", cause)) from error
            if isinstance(cause, TemplateSyntaxError):
                filename = Path(cause.filename) if cause.filename else source
                if filename.is_relative_to(templates):
                    original = inventory.original / filename.relative_to(templates)
                    raise InvalidArtifact(f"invalid Jinja syntax in {inventory.local(original)} at line {cause.lineno}") from error
            cause = cause.__cause__
        if isinstance(error.__cause__, (ValueError, TypeError, ArithmeticError, TemplateError)):
            raise InvalidArtifact(f"takler rejected the isolated job template from {local}") from error
        raise Unavailable("takler could not complete native job creation") from error
    if not expected.is_file() or not expected.stat().st_mode & 0o100:
        raise Unavailable("takler did not create the executable job in the temporary directory")
    return expected
