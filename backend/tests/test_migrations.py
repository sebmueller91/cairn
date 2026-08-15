import os
import subprocess
import sys
import tempfile

from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_head_creates_account_table():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(db_path)  # alembic/sqlite creates it fresh
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        env = {**os.environ, "DATABASE_PATH": db_path}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=backend_dir,
            env=env,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

        engine = create_engine(f"sqlite:///{db_path}")
        tables = inspect(engine).get_table_names()
        assert "account" in tables
        assert "alembic_version" in tables
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
