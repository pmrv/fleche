from abc import ABC, abstractmethod
from dataclasses import dataclass
import getpass
import os
import socket
import subprocess
import time
from typing import Any, TypeAlias

from .call import Call

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

    @property
    @abstractmethod
    def keys(self) -> dict[str, type]:
        """
        Defines the schema of the metadata, mapping metadata keys to their expected types.

        Returns:
            dict[str, type]: A dictionary representing the metadata schema.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """
        The unique name of this metadata type.

        Returns:
            str: The name of the metadata type.
        """
        ...


class Runtime(MetaData):
    """Metadata type for capturing runtime information.

    Keys:
        timestart (float): The timestamp when the execution started.
        timestop (float): The timestamp when the execution stopped.
        walltime (float): The total execution time in seconds.

    Notes:
        Values are JSON-serializable.
    """
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

    name: str = 'runtime'
    keys: dict[str, type] = {
            'timestart': float,
            'timestop': float,
            'walltime': float,
    }


class Environment(MetaData):
    """Metadata type for capturing the execution environment.

    Keys:
        hostname (str): The machine hostname (``socket.gethostname()``).
        username (str): The current user (``getpass.getuser()``).
        cwd (str): The working directory at call time (``os.getcwd()``).
    """
    def pre(self, call: Call) -> dict[str, Any]:
        return {
            'hostname': socket.gethostname(),
            'username': getpass.getuser(),
            'cwd': os.getcwd(),
        }

    name: str = 'environment'
    keys: dict[str, type] = {
            'hostname': str,
            'username': str,
            'cwd': str,
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

    name: str = 'git'
    keys: dict[str, type] = {
            'root': str,
            'commit': str,
            'branch': str,
            'dirty': bool,
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
