from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def test_doctor_database_audit_uses_sqlite_compile_options():
    from app.domains.system.doctor import DoctorService

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE contents (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE sources (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))

    with Session(engine) as db:
        result = DoctorService(db)._audit_database()

    assert result["status"] in {"ok", "warning"}
    assert result["version"]
    assert result["is_migrated"] is True
