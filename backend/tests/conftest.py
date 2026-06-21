# conftest.py — makes the backend directory importable during tests
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
