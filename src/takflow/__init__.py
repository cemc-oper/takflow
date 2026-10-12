"""takflow — unified workflow-generation framework.

Provides the generic layer shared by the domain applications: the ``jobspec``
contract, flow/backend abstraction, hooks, config base, and the
job/resource/credential/util toolkit (see
``framework/doc/TAKFLOW_DESIGN.md`` in the workspace).
"""

try:
    from ._version import version as __version__
except ImportError:  # pragma: no cover
    __version__ = "unknown"

__all__ = ["__version__"]
