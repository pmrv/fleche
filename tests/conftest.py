import os
import sys

from hypothesis import settings
from hypothesis.database import (
    DirectoryBasedExampleDatabase,
    GitHubArtifactDatabase,
    MultiplexedDatabase,
    ReadOnlyDatabase,
)

pytest_plugins = ["tests.fixtures"]

# Make CPython's own `test` package unimportable on every interpreter, as it
# already is on builds that leave it out (uv's managed Pythons).  Tests must
# never name `test` as a module: where the package exists, an import of it
# succeeds and silently takes a different code path than in CI.
sys.modules["test"] = None  # type: ignore[assignment]

if os.environ.get("GITHUB_ACTIONS") == "true":
    _local = DirectoryBasedExampleDatabase(".hypothesis/examples")
    _shared = ReadOnlyDatabase(
        GitHubArtifactDatabase(
            "pmrv",
            "fleche",
            artifact_name=os.environ.get(
                "HYPOTHESIS_ARTIFACT_NAME", "hypothesis-example-db"
            ),
        )
    )
    settings.register_profile("ci", database=MultiplexedDatabase(_local, _shared))
    settings.load_profile("ci")
