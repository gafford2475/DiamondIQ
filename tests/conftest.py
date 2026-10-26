import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="diamondiq-test-")
os.environ["DIAMONDIQ_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["DIAMONDIQ_MEDIA_DIR"] = f"{_tmp}/media"
os.environ["DIAMONDIQ_PROJECTION_SIMS"] = "400"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
