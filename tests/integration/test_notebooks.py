import pytest
from pathlib import Path
import subprocess

NOTEBOOKS_DIR = Path(__file__).parents[2] / "notebooks"
# Discovered rather than listed: a hand-maintained list silently stops covering
# notebooks added later, and those are exactly the ones that rot.
NOTEBOOKS = sorted(p.name for p in NOTEBOOKS_DIR.glob("*.ipynb"))


@pytest.mark.parametrize("notebook", NOTEBOOKS)
def test_notebook(notebook):
    notebook_path = NOTEBOOKS_DIR / notebook
    cmd = [
        "jupyter",
        "nbconvert",
        "--to",
        "notebook",
        "--execute",
        str(notebook_path),
        "--stdout",
    ]
    # We want to capture stderr to see the error if it fails
    result = subprocess.run(cmd, stderr=subprocess.STDOUT, text=True)
    assert result.returncode == 0, f"Notebook {notebook} failed:\n{result.stdout}"
