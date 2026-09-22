"""Put `src` on sys.path so the tests import `imagesorter` from the source tree."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
