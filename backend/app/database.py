from sqlmodel import SQLModel, Session, create_engine
from app.config import settings

engine = create_engine(settings.database_url, echo=False)


def init_db():
    SQLModel.metadata.create_all(engine)
    _ensure_lightweight_migrations()


def get_session():
    with Session(engine) as session:
        yield session


INCIDENT_COLUMNS = {
    "agent_severity": "VARCHAR",
    "escalate": "BOOLEAN",
    "escalation_reason": "VARCHAR",
    "assessor": "VARCHAR",
    "assessed_at": "DATETIME",
}


def _ensure_lightweight_migrations():
    with engine.begin() as connection:
        incident_info = connection.exec_driver_sql("PRAGMA table_info(incident)").fetchall()
        incident_columns = {row[1] for row in incident_info}

        for name, sql_type in INCIDENT_COLUMNS.items():
            if incident_info and name not in incident_columns:
                connection.exec_driver_sql(f"ALTER TABLE incident ADD COLUMN {name} {sql_type}")

        table_info = connection.exec_driver_sql("PRAGMA table_info(recommendation)").fetchall()

        if not table_info:
            return

        columns = {row[1] for row in table_info}

        if "workflow_notes" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE recommendation ADD COLUMN workflow_notes VARCHAR NOT NULL DEFAULT ''"
            )
