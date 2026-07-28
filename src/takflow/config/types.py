"""配置字段类型与 ecFlow 变量装配辅助。

本模块提供两类设施，供各应用在 Pydantic 配置模型与 ecFlow 变量之间搭桥：

- :data:`FortranBool` — Fortran namelist 布尔类型。YAML 按原生 bool
  （``true``/``false``）填写；python 模式（``model_dump()``）仍是 ``bool``，
  JSON 模式（``model_dump(mode="json")``）序列化为 ``.true.``/``.false.``
  字面量。
- :func:`fortran_variables` / :func:`flag_variables` — 把配置模型装配为可直接
  传给 ``Node.add_variables()`` 的字符串字典。

.. warning::

   ecFlow 序列化器（``_stringify``）会把泄露的 Python ``True``/``False`` 写成
   ``edit X 1``/``edit X 0``。凡含布尔语义的字段必须使用 :data:`FortranBool`
   并经由 :func:`fortran_variables` 装配；两个装配函数会对仍是 ``bool`` 的
   值（即字段误声明为普通 ``bool``）抛出 :class:`TypeError`，而不是静默写错 def。
"""
from __future__ import annotations

from typing import Dict

from pydantic import BaseModel, PlainSerializer
from typing_extensions import Annotated


def _serialize_fortran_bool(value: bool) -> str:
    return ".true." if value else ".false."


FortranBool = Annotated[
    bool,
    PlainSerializer(_serialize_fortran_bool, return_type=str, when_used="json"),
]
"""Fortran namelist 布尔：YAML 写 bool，JSON 模式序列化为 ``.true.``/``.false.``。"""


def _dump_string_dict(model: BaseModel, *, _caller: str) -> Dict[str, str]:
    """model_dump(mode="json") 并统一转 str；拒绝仍是 bool 的泄露值。"""
    dumped = model.model_dump(mode="json")
    result: Dict[str, str] = {}
    for key, value in dumped.items():
        if isinstance(value, bool):
            raise TypeError(
                f"{_caller}: 字段 {key!r} 序列化后仍是 Python bool——"
                f"请把该字段声明为 FortranBool，否则 def 中会被写成 1/0"
            )
        result[key] = str(value)
    return result


def fortran_variables(model: BaseModel) -> Dict[str, str]:
    """把参数模型装配为可直接 ``add_variables`` 的字符串字典。

    强制使用 ``mode="json"``，保证 :data:`FortranBool` 字段输出
    ``.true.``/``.false.`` 而非 ``True``/``False``；int/str 等其余字段统一
    转为 ``str``。字典顺序 = 模型字段定义顺序。
    """
    return _dump_string_dict(model, _caller="fortran_variables")


def flag_variables(model: BaseModel, *, prefix: str = "FLAG_") -> Dict[str, str]:
    """把开关模型装配为 ``FLAG_<UPPER>`` 变量字典（gfs-post 命名约定）。

    小写字段名转大写并加 ``prefix``；字段应为 :data:`FortranBool`，
    值为 ``.true.``/``.false.``。字典顺序 = 模型字段定义顺序。
    """
    variables = _dump_string_dict(model, _caller="flag_variables")
    return {f"{prefix}{key.upper()}": value for key, value in variables.items()}
