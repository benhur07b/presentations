import sys
from pathlib import Path

# The tests import the scripts they test, from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
