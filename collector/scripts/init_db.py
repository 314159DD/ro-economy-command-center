"""Apply schema.sql to DATABASE_URL. Usage: .venv\\Scripts\\python scripts/init_db.py"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[0].parent))
from ro_collector.config import load_settings  # noqa: E402
from ro_collector.db import Store  # noqa: E402

schema = (pathlib.Path(__file__).resolve().parents[1] / "schema.sql").read_text(encoding="utf-8")
Store(load_settings().database_url).init_schema(schema)
print("schema applied")
