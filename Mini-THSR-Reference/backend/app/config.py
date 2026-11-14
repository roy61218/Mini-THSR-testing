from datetime import date
from pathlib import Path
import os

START_DATE = date(2026, 12, 1)
END_DATE = date(2027, 1, 31)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data"))
SCHEMA_FILE = Path(os.environ.get("SCHEMA_FILE", PROJECT_ROOT / "schema/schema.sql"))
