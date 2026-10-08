# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# -- Path setup --------------------------------------------------------------
# 项目 src 目录（docs 位于 takflow/docs/source/）
sys.path.insert(0, os.path.abspath("../../src"))

# -- Project information -----------------------------------------------------
project = "takflow"
copyright = "2024-2026, cemc-oper"
author = "cemc-oper"

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns = []

language = "zh_CN"

# -- Suppress warnings -------------------------------------------------------
suppress_warnings = ["ref.python"]

# -- Options for autodoc -----------------------------------------------------
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}
autodoc_member_order = "bysource"

# -- Options for Napoleon (NumPy/Google style docstrings) --------------------
napoleon_numpy_docstring = True
napoleon_google_docstring = False

# -- Options for intersphinx -------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}

# -- Options for MyST parser -------------------------------------------------
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}
myst_enable_extensions = [
    "colon_fence",
    "fieldlist",
]

# -- Options for HTML output -------------------------------------------------
html_theme = "pydata_sphinx_theme"
html_theme_options = {
    "github_url": "https://github.com/cemc-oper/takflow",
    "show_toc_level": 2,
    "navigation_with_keys": False,
}
html_title = "takflow"

# -- Resolve napoleon/autodoc duplicate attribute entries --------------------
# 类 docstring 的 numpy 风格 "Attributes" 段由 napoleon 渲染成带描述的属性条目；
# autodoc 又会把带注解的类字段/property 自动文档化成第二条（无描述）重复条目。
# 这里跳过 autodoc 生成的那份，保留 napoleon 版本。
#
# 注意两个实现约束（Sphinx 9 实测）：
# 1. autodoc-skip-member 的 what 是“容器”类型：类成员恒为 "class"，事件中
#    拿不到所属类；
# 2. automodule 会先处理完模块内所有类的 docstring 事件，再批量触发成员
#    skip 事件，无法按“当前类”跟踪。
# 因此按模块取并集：模块内所有类的 Attributes 段条目合并为一个集合，
# 成员名命中即跳过。同模块内“一个类的属性名与另一个类的方法名撞名”时
# 会误伤，需在添加 Attributes 段时留意（当前代码无此情况）。
import inspect
import re
from inspect import cleandoc


def _attributes_section_names(docstring: str):
    """Return attribute names listed in a numpy-style Attributes section."""
    doc = cleandoc(docstring or "")
    m = re.search(r"(?ms)^Attributes\s*\n-+\s*\n(.*?)(?=^\S[^\n]*\n-{3,}\s*$|\Z)", doc)
    if not m:
        return frozenset()
    return frozenset(re.findall(r"(?m)^(\w+)\s*:", m.group(1)))


def _module_attributes_union(module):
    """Union of Attributes-section entries over the module's own classes."""
    names = set()
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if cls.__module__ == module.__name__:
            names.update(_attributes_section_names(cls.__doc__))
    return frozenset(names)


def _track_current_module(app, what, name, obj, options, lines):
    if what == "module" and obj is not None:
        app.env._takflow_module_attributes = _module_attributes_union(obj)


def _skip_napoleon_attribute_duplicates(app, what, name, obj, skip, options):
    if skip or what != "class":
        return skip
    if name in getattr(app.env, "_takflow_module_attributes", frozenset()):
        return True
    return skip


def setup(app):
    app.connect("autodoc-process-docstring", _track_current_module)
    app.connect("autodoc-skip-member", _skip_napoleon_attribute_duplicates)


