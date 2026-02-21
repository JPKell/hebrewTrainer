"""
PythonAnywhere WSGI entry point.

In the PythonAnywhere Web tab:
  - Source code:    /home/<your-username>/hebrewTrainer
  - Working dir:    /home/<your-username>/hebrewTrainer
  - WSGI file:      /home/<your-username>/hebrewTrainer/wsgi.py
  - Virtualenv:     /home/<your-username>/hebrewTrainer/.venv
"""
import sys
import os

# Make sure the project directory is on the path
project_dir = os.path.dirname(os.path.abspath(__file__))
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

from app import app as application  # noqa: F401  (PythonAnywhere looks for 'application')
