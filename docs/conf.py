import os
import sys
sys.path.insert(0, os.path.abspath('../src'))

project = 'Fleche'
copyright = '2024, Marvin Poul'
author = 'Marvin Poul'

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
    'autoapi.extension',
    'sphinx_rtd_theme',
    'nbsphinx',
]

intersphinx_mapping = {
    'python': ('https://docs.python.org/3/', None),
    'pandas': ('https://pandas.pydata.org/docs/', None),
    'bagofholding': ('https://bagofholding.readthedocs.io/en/latest/', None),
}

# `Keys:` blocks document the entries a MetaData subclass stores; teaching
# napoleon about them renders those blocks like an `Args:` section instead of
# an unparsed, badly indented block quote.
napoleon_custom_sections = [("Keys", "params_style")]

# Cross-references autoapi generates from annotations that have nowhere to
# point: `...` inside `Callable[..., T]` / `tuple[T, ...]` is emitted as a
# class reference to `Ellipsis`, and `fleche.remote` defines __all__, so its
# private `_Connection` is never documented.
nitpick_ignore = [
    ("py:class", "Ellipsis"),
    ("py:class", "_Connection"),
]

nbsphinx_execute = 'never'

autoapi_dirs = ['../src']
autoapi_ignore = ['*fleche/_version.py']
autoapi_add_toctree_entry = False

html_theme = 'sphinx_rtd_theme'
templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
