# PythonAnywhere: set your project directory in the Web app's "Code" section,
# then set "WSGI configuration file" to: wsgi.py (or path to this file).
# This file loads the Flask app as "application".

import sys
from pathlib import Path

# Ensure project root is on the path (optional; PA often sets working directory)
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from application import application
