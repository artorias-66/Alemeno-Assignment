"""
conftest.py — adds the backend directory to sys.path so pytest can import
utils, tasks, models, etc. without requiring the package to be installed.
"""
import sys
import os

# Insert the backend/ directory (parent of this tests/ folder) at the front
# of sys.path so `from utils import clean_data` resolves correctly regardless
# of where pytest is invoked from.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
