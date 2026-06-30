"""takflow — unified workflow-generation framework.

Phase 0 exposes the ``jobspec`` contract layer. Later phases add the engine
abstraction, hooks, config base, job/resource/credential/util, and the CLI
skeleton (see ``../TAKFLOW_DESIGN.md``).
"""

try:
    from ._version import version as __version__
except ImportError:  # pragma: no cover
    __version__ = "unknown"

__all__ = ["__version__"]
