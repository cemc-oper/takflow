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
# 这里跳过 autodoc 生成的那份：凡属性名出现在所属类 "Attributes" 段中的，
# 跳过 autodoc 的 attribute/property 成员条目，保留 napoleon 版本。
import importlib
import re
from functools import lru_cache
from inspect import cleandoc


@lru_cache(maxsize=None)
def _attributes_section_names(class_name: str):
    """Return attribute names listed in the class docstring's Attributes section."""
    module_name, _, attr_path = class_name.rpartition(".")
    try:
        cls = getattr(importlib.import_module(module_name), attr_path)
    except (ImportError, AttributeError):
        return frozenset()
    doc = cleandoc(cls.__doc__ or "")
    m = re.search(r"(?ms)^Attributes\s*\n-+\s*\n(.*?)(?=^\S|\Z)", doc)
    if not m:
        return frozenset()
    return frozenset(re.findall(r"(?m)^(\w+)\s*:", m.group(1)))


def _skip_napoleon_attribute_duplicates(app, what, name, obj, skip, options):
    if skip or what not in ("attribute", "property"):
        return skip
    class_name = app.env.ref_context.get("py:class")
    if class_name and name in _attributes_section_names(class_name):
        return True
    return skip


def setup(app):
    app.connect("autodoc-skip-member", _skip_napoleon_attribute_duplicates)
