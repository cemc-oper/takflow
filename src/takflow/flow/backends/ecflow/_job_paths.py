"""Resolve the local template paths used by generated ecFlow definitions."""
from pathlib import Path
import shlex


def ecflow_templates(node_path, variables):
    command = variables.get("ECF_SCRIPT_CMD")
    if command:
        try:
            words = shlex.split(command)
        except ValueError:
            return ()
        if len(words) == 2 and words[0] == "cat" and command == "cat " + shlex.quote(words[1]):
            path = Path(words[1])
            if path.is_absolute():
                return (path,)
        return ()
    directory = variables.get("ECF_FILES")
    if not directory or not Path(directory).is_absolute():
        return ()
    parts = Path(node_path.lstrip("/")).parts
    suffix = variables.get("ECF_EXTN", ".ecf")
    if variables.get("ECF_FILES_LOOKUP", "").lower() == "prune_leaf":
        return tuple(Path(directory, *parts[:index], parts[-1] + suffix) for index in reversed(range(len(parts))))
    return tuple(Path(directory, *parts[index:-1], parts[-1] + suffix) for index in range(len(parts)))


def ecflow_task_templates(suite):
    def visit(node, inherited):
        variables = inherited | node.raw._variables
        if node.node_type.value == "task":
            yield node, ecflow_templates(node.path, variables)
        for child in node.children:
            yield from visit(child, variables)

    yield from visit(suite, {})
