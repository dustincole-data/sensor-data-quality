"""Put the repo root on sys.path so tests import `src.*` when run from anywhere."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
