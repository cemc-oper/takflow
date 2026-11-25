"""Import contracts for the reorganized public packages."""

from importlib.util import find_spec

import pytest

from takflow import build_info, flow


@pytest.mark.parametrize("name", [
    "takflow.toolkit",
    "takflow.backends",
    "takflow.generation",
    "takflow.artifact_checks",
    "takflow._native_artifacts",
    "takflow._job_paths",
])
def test_retired_module_paths_are_absent(name):
    assert find_spec(name) is None


def test_retired_aliases_are_absent():
    assert "register_hook" not in flow.__all__
    assert not hasattr(flow, "register_hook")
    assert "set_build_info_provider" not in build_info.__all__
    assert not hasattr(build_info, "set_build_info_provider")
