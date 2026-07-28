"""Unit tests for takflow.config.types (FortranBool & variable assembly helpers)."""
from __future__ import annotations

import pytest
import yaml
from pydantic import BaseModel, ConfigDict

from takflow.config import FortranBool, flag_variables, fortran_variables


class ParamsConfig(BaseModel):
    """Mixed parameter model mimicking an app's parameters section."""

    model_config = ConfigDict(extra="forbid")

    enable_ncep_gfs: FortranBool
    do_blending: FortranBool
    do_iau: int
    res: str


class FlagsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hpc_archive_model: FortranBool
    hpc_archive_modelvar: FortranBool


def _load_params() -> ParamsConfig:
    data = yaml.safe_load(
        """
        enable_ncep_gfs: true
        do_blending: false
        do_iau: 0
        res: 9km
        """
    )
    return ParamsConfig(**data)


def test_fortran_bool_loads_from_yaml_bool():
    params = _load_params()
    assert params.enable_ncep_gfs is True
    assert params.do_blending is False
    assert params.do_iau == 0
    assert params.res == "9km"


def test_python_mode_dump_keeps_bool():
    dumped = _load_params().model_dump()
    assert dumped["enable_ncep_gfs"] is True
    assert dumped["do_blending"] is False


def test_json_mode_dump_serializes_fortran_literals():
    dumped = _load_params().model_dump(mode="json")
    assert dumped["enable_ncep_gfs"] == ".true."
    assert dumped["do_blending"] == ".false."
    assert dumped["do_iau"] == 0
    assert dumped["res"] == "9km"


def test_fortran_variables_returns_string_dict_in_field_order():
    variables = fortran_variables(_load_params())
    assert variables == {
        "enable_ncep_gfs": ".true.",
        "do_blending": ".false.",
        "do_iau": "0",
        "res": "9km",
    }
    assert all(isinstance(value, str) for value in variables.values())
    # 字典顺序 = 字段定义顺序（golden diff 约束）
    assert list(variables) == ["enable_ncep_gfs", "do_blending", "do_iau", "res"]


def test_flag_variables_uppercases_and_prefixes():
    flags = FlagsConfig(hpc_archive_model=True, hpc_archive_modelvar=False)
    assert flag_variables(flags) == {
        "FLAG_HPC_ARCHIVE_MODEL": ".true.",
        "FLAG_HPC_ARCHIVE_MODELVAR": ".false.",
    }


def test_plain_bool_field_is_rejected_by_fortran_variables():
    """普通 bool 字段会泄露为 def 里的 1/0，必须报错而不是静默通过。"""

    class BadConfig(BaseModel):
        enable_x: bool

    with pytest.raises(TypeError, match="FortranBool"):
        fortran_variables(BadConfig(enable_x=True))

    with pytest.raises(TypeError, match="FortranBool"):
        flag_variables(BadConfig(enable_x=False))
