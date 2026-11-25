"""takflow — unified workflow-generation framework.

Provides the generic layer shared by the domain applications: the ``jobspec``
contract, flow/backend abstraction, hooks, config base, and the
job/resource/credential/util toolkit. See ``docs/source/develop/architecture.md``
in the takflow repository.
"""

try:
    from ._version import version as __version__
except ImportError:  # pragma: no cover
    __version__ = "unknown"

__all__ = ["__version__"]
