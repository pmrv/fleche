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
    'bagofholding': ('https://bagofholding.readthedocs.io/en/latest/', None),
}

nbsphinx_execute = 'never'

autoapi_dirs = ['../src']
autoapi_ignore = ['*fleche/_version.py']
autoapi_add_toctree_entry = False

html_theme = 'sphinx_rtd_theme'
templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
