from abc import ABC
from dataclasses import dataclass
import getpass
import os
import platform
import socket
import subprocess
import sys
import time
import types
from typing import Any, ClassVar, TypeAlias

from .call import Call

try:
    from ._version import __version__ as _fleche_version
except ImportError:
    _fleche_version = "unknown"

try:
    import resource as _resource_module
    resource: types.ModuleType | None = _resource_module
except ImportError:  # pragma: no cover - resource is POSIX-only, no Windows CI
    resource = None

# Values produced by MetaData.pre/post must be JSON-serializable.
# This alias documents the expected shape and helps static type checkers.
JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]


class MetaData(ABC):
    """Abstract base class for defining metadata types.

    Implementations must return only JSON-serializable values from pre() and post().
    That means scalars (str, int, float, bool, None), lists of those, or dicts with str keys
    and JSON-serializable values.
    """
    def pre(self, call: Call) -> dict[str, JSONValue]:
        """
        Hook for collecting metadata before the function execution.

        Args:
            call (Call): The call object of the decorated function.

        Returns:
            dict[str, JSONValue]: A flat dictionary of JSON-serializable metadata collected before execution.
        """
        return {}

    def post(self, pre: dict[str, JSONValue], call: Call) -> dict[str, JSONValue]:
        """
        Hook for collecting metadata after the function execution.

        The return value of the function is available on the `call.result` attribute.

        Args:
            pre (dict[str, JSONValue]): Metadata collected during the pre-execution phase.
            call (Call): The call object of the decorated function.

        Returns:
            dict[str, JSONValue]: A flat dictionary of JSON-serializable metadata collected after execution.
        """
        return {}

    _keys: ClassVar[dict[str, type]] = {}
    """Constant schema for subclasses whose keys don't depend on instance state.

    Subclasses with a static schema declare this once instead of overriding
    ``keys``; subclasses whose schema depends on instance state (e.g. ``Tags``)
    override the ``keys`` property directly instead.
    """

    @property
    def keys(self) -> dict[str, type]:
        """
        Defines the schema of the metadata, mapping metadata keys to their expected types.

        Returns:
            dict[str, type]: A dictionary representing the metadata schema.
        """
        return self._keys

    name: str
    """The unique name of this metadata type."""


CONFIGURABLE: dict[str, type["MetaData"]] = {}


def configurable(cls: type["MetaData"]) -> type["MetaData"]:
    """Register a MetaData subclass as zero-arg configurable and set its name.

    Sets ``cls.name`` to ``cls.__name__.lower()`` and adds the class to the
    ``CONFIGURABLE`` registry under ``cls.__name__``, making it selectable from
    the TOML ``[default] metadata = [...]`` list.  Classes that require
    constructor arguments (e.g. ``Tags``) must **not** be decorated.
    """
    cls.name = cls.__name__.lower()
    CONFIGURABLE[cls.__name__] = cls
    return cls


@configurable
class Runtime(MetaData):
    """Metadata type for capturing runtime information.

    Keys:
        timestart (float): The timestamp when the execution started.
        timestop (float): The timestamp when the execution stopped.
        walltime (float): The total execution time in seconds.

    Notes:
        Values are JSON-serializable.
    """
    _keys: ClassVar[dict[str, type]] = {
        'timestart': float,
        'timestop': float,
        'walltime': float,
    }

    def pre(self, call: Call) -> dict[str, Any]:
        """
        Records the start time before function execution.
        """
        return {'timestart': time.time()}

    def post(self, pre: dict[str, Any], call: Call) -> dict[str, Any]:
        """
        Records the stop time and calculates the wall time after function execution.
        """
        return {
            'timestop': (t := time.time()),
            'walltime': t - pre['timestart'],
        }


@configurable
class Environment(MetaData):
    """Metadata type for capturing the execution environment.

    Keys:
        hostname (str): The machine hostname (``socket.gethostname()``).
        username (str): The current user (``getpass.getuser()``).
        cwd (str): The working directory at call time (``os.getcwd()``).
        fleche_version (str): The fleche package version (``fleche.__version__``);
            ``"unknown"`` when the package was imported without an installed
            ``_version.py`` (e.g. an editable checkout without a build).
        python_version (str): The CPython runtime version (``platform.python_version()``).
    """
    _keys: ClassVar[dict[str, type]] = {
        'hostname': str,
        'username': str,
        'cwd': str,
        'fleche_version': str,
        'python_version': str,
    }

    def pre(self, call: Call) -> dict[str, Any]:
        return {
            'hostname': socket.gethostname(),
            'username': getpass.getuser(),
            'cwd': os.getcwd(),
            'fleche_version': _fleche_version,
            'python_version': platform.python_version(),
        }


def _git(*args: str) -> str | None:
    """Run ``git`` with *args* and return stripped stdout, or ``None`` on failure."""
    try:
        result = subprocess.run(
                ('git', *args),
                capture_output=True, text=True, check=False, timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


@configurable
class Git(MetaData):
    """Metadata type for capturing the git state of the working directory.

    Keys:
        root (str | None): Repository top level (``git rev-parse --show-toplevel``).
        commit (str | None): HEAD commit SHA (``git rev-parse HEAD``).
        branch (str | None): Current branch name (``git rev-parse --abbrev-ref HEAD``);
            ``"HEAD"`` when in detached-HEAD state.
        dirty (bool | None): ``True`` if there are uncommitted changes
            (tracked or untracked), ``False`` otherwise; ``None`` when not
            inside a repository or git is unavailable.

    All keys are ``None`` when not inside a git repository or when the ``git``
    executable is missing.
    """
    _keys: ClassVar[dict[str, type]] = {
        'root': str,
        'commit': str,
        'branch': str,
        'dirty': bool,
    }

    def pre(self, call: Call) -> dict[str, Any]:
        root = _git('rev-parse', '--show-toplevel')
        if root is None:
            return {'root': None, 'commit': None, 'branch': None, 'dirty': None}
        status = _git('status', '--porcelain')
        return {
            'root': root,
            'commit': _git('rev-parse', 'HEAD'),
            'branch': _git('rev-parse', '--abbrev-ref', 'HEAD'),
            'dirty': bool(status) if status is not None else None,
        }


def _rusage_totals() -> tuple[Any, Any]:
    """``(RUSAGE_SELF, RUSAGE_CHILDREN)`` snapshots, fetched together so a
    ``pre``/``post`` pair sees a consistent self+children split.

    Callers must only reach this after their own ``resource is None`` guard.
    """
    assert resource is not None
    return resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)


def _cpu_seconds(ru_self: Any, ru_children: Any) -> tuple[float, float]:
    """``(user, sys)`` CPU seconds, self + children combined."""
    return ru_self.ru_utime + ru_children.ru_utime, ru_self.ru_stime + ru_children.ru_stime


def _maxrss_bytes(ru_self: Any, ru_children: Any) -> int:
    """Peak RSS across self + children, normalized to bytes.

    ``ru_maxrss`` is reported in KiB on Linux but bytes on macOS/BSD.
    """
    peak = max(ru_self.ru_maxrss, ru_children.ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


@configurable
class Resources(MetaData):
    """Metadata type for capturing resource consumption during a call.

    Keys:
        peak_rss (int | None): Peak resident-set size in bytes, across the
            process and any children it spawned, sampled via
            ``resource.getrusage`` at call end.  ``None`` where the POSIX
            ``resource`` module is unavailable (Windows).
        user_cpu (float | None): User-mode CPU seconds consumed during the
            call (self + child processes).  ``None`` where unavailable.
        sys_cpu (float | None): Kernel-mode CPU seconds consumed during the
            call (self + child processes).  ``None`` where unavailable.

    Notes:
        - POSIX-only (backed by the stdlib ``resource`` module); all keys are
          ``None`` on platforms without it (Windows) rather than raising.
        - ``peak_rss`` reflects ``ru_maxrss``, which is a monotonically
          non-decreasing high-water mark over the *whole process lifetime*,
          not a peak scoped to this call — it overstates a call's own
          footprint when the process peaked earlier, and cannot see memory
          released since.  A tighter per-call bound would need a background
          sampler thread; out of scope here.
        - CPU seconds sum ``RUSAGE_SELF`` and ``RUSAGE_CHILDREN``, so a call
          that shells out to a subprocess (e.g. ``git``, ``mpirun``) has that
          cost accounted for.
        - ``resource.getrusage`` is process-wide, so this is only meaningful
          for sequential call sites: overlapping ``@fleche``-wrapped calls
          (executor workers, threads, async) will see each other's CPU time
          and RSS bleed into their own deltas.
    """
    _keys: ClassVar[dict[str, type]] = {
        'peak_rss': int,
        'user_cpu': float,
        'sys_cpu': float,
    }

    def pre(self, call: Call) -> dict[str, Any]:
        if resource is None:
            return {}
        user, sys_ = _cpu_seconds(*_rusage_totals())
        return {'user_cpu': user, 'sys_cpu': sys_}

    def post(self, pre: dict[str, Any], call: Call) -> dict[str, Any]:
        if resource is None:
            return {'peak_rss': None, 'user_cpu': None, 'sys_cpu': None}
        ru_self, ru_children = _rusage_totals()
        user, sys_ = _cpu_seconds(ru_self, ru_children)
        return {
            'peak_rss': _maxrss_bytes(ru_self, ru_children),
            'user_cpu': user - pre.get('user_cpu', user),
            'sys_cpu': sys_ - pre.get('sys_cpu', sys_),
        }


@dataclass
class Tags(MetaData):
    """Metadata type for storing arbitrary tags.

    For each key in the ``tags`` dictionary, a new metadata column is created.

    Keys:
        tags (dict): A dictionary of user-defined tags.

    Notes:
        Tag values must be JSON-serializable.
    """
    tags: dict[str, Any]

    def pre(self, call: Call) -> dict[str, Any]:
        return self.tags.copy()

    name: str = "tags"

    @property
    def keys(self):
        return {k: type(v) for k, v in self.tags.items()}
