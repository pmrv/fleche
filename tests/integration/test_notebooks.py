import os
import pytest
from pathlib import Path
import subprocess

NOTEBOOKS_DIR = Path(__file__).parents[2] / "notebooks"
NOTEBOOKS = [
    n.name for n in NOTEBOOKS_DIR.glob("*.ipynb")
]

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
