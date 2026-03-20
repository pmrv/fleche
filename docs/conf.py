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
    'autoapi.extension',
    'sphinx_rtd_theme',
    'nbsphinx',
]

nbsphinx_execute = 'never'

autoapi_dirs = ['../src']
autoapi_ignore = ['*fleche/_version.py']

html_theme = 'sphinx_rtd_theme'
templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
