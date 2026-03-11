"""Pytest conftest to ensure project root is on sys.path during test collection.

This makes absolute imports like 'from app.services.pubmed import ...' work when
running pytest from the project directory or via an activated venv where the
current working directory was not automatically added to sys.path.
"""
from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    # insert at position 0 so local packages take precedence
    sys.path.insert(0, str(project_root))
