"""Create the shared database helper used by the application.

The Flask application connects this helper to its settings in main.py.
Other files use it to describe database tables and work with saved data.
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
