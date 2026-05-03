from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app.db import models  # noqa: F401

    _run_schema_migrations()
    Base.metadata.create_all(bind=engine)
    _run_post_create_migrations()


def _run_schema_migrations() -> None:
    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())

        if "curriculum_nodes" in tables and "curriculum_constant_nodes" not in tables:
            conn.execute(text("ALTER TABLE curriculum_nodes RENAME TO curriculum_constant_nodes"))
            tables.remove("curriculum_nodes")
            tables.add("curriculum_constant_nodes")

        if "yaml_templates" in tables:
            cols = {c["name"] for c in inspect(conn).get_columns("yaml_templates")}
            if "curriculum_node_id" in cols and "curriculum_folder_node_id" not in cols:
                conn.execute(text("ALTER TABLE yaml_templates RENAME COLUMN curriculum_node_id TO curriculum_folder_node_id"))

        if "property_definitions" in tables:
            cols = {c["name"] for c in inspect(conn).get_columns("property_definitions")}
            if "label" not in cols:
                conn.execute(text("ALTER TABLE property_definitions ADD COLUMN label TEXT"))
            if "description" not in cols:
                conn.execute(text("ALTER TABLE property_definitions ADD COLUMN description TEXT"))
            if "default_value" not in cols:
                conn.execute(text("ALTER TABLE property_definitions ADD COLUMN default_value TEXT"))
            conn.execute(text("UPDATE property_definitions SET label = COALESCE(NULLIF(label, ''), property_key)"))


def _run_post_create_migrations() -> None:
    with engine.begin() as conn:
        dialect = conn.dialect.name
        if dialect != "postgresql":
            return

        # Move non-constant legacy nodes into folder table while preserving ids.
        conn.execute(
            text(
                """
                INSERT INTO curriculum_folder_nodes (
                    id, parent_id, node_type, name, slug, code, sort_order, depth, path,
                    grade, subject, theme, is_active, created_at, updated_at
                )
                SELECT
                    c.id,
                    CASE
                        WHEN p.id IS NULL THEN NULL
                        WHEN p.node_type IN ('root','grade','subject','theme') THEN NULL
                        ELSE c.parent_id
                    END AS parent_id,
                    'folder',
                    c.name,
                    c.slug,
                    c.code,
                    c.sort_order,
                    c.depth,
                    c.path,
                    split_part(c.path, '/', 2) AS grade,
                    split_part(c.path, '/', 3) AS subject,
                    split_part(c.path, '/', 4) AS theme,
                    c.is_active,
                    c.created_at,
                    c.updated_at
                FROM curriculum_constant_nodes c
                LEFT JOIN curriculum_constant_nodes p ON p.id = c.parent_id
                WHERE c.node_type NOT IN ('root','grade','subject','theme')
                  AND NOT EXISTS (
                      SELECT 1
                      FROM curriculum_folder_nodes f
                      WHERE f.id = c.id
                  )
                """
            )
        )

        fk_rows = conn.execute(
            text(
                """
                SELECT c.conname, t.relname AS table_name, pg_get_constraintdef(c.oid) AS def
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE n.nspname = 'public' AND c.contype = 'f'
                """
            )
        ).mappings()

        for row in fk_rows:
            table_name = row["table_name"]
            conname = row["conname"]
            definition = row["def"] or ""

            if table_name == "property_definitions" and "defined_at_curriculum_node_id" in definition:
                conn.execute(text(f'ALTER TABLE "property_definitions" DROP CONSTRAINT "{conname}"'))

            if table_name == "yaml_templates" and "curriculum_folder_node_id" in definition and "curriculum_folder_nodes" not in definition:
                conn.execute(text(f'ALTER TABLE "yaml_templates" DROP CONSTRAINT "{conname}"'))

        # Remove old rows from constant table after FK detachment.
        conn.execute(
            text(
                """
                DELETE FROM curriculum_constant_nodes
                WHERE node_type NOT IN ('root','grade','subject','theme')
                """
            )
        )

        # Normalize legacy yaml_templates index/constraint names if present.
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conname = 'uq_yaml_templates_curriculum_node_id'
                    ) THEN
                        ALTER TABLE yaml_templates
                        RENAME CONSTRAINT uq_yaml_templates_curriculum_node_id
                        TO uq_yaml_templates_curriculum_folder_node_id;
                    END IF;
                END $$;
                """
            )
        )
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND indexname = 'ix_yaml_templates_curriculum_node_id'
                    ) THEN
                        ALTER INDEX ix_yaml_templates_curriculum_node_id
                        RENAME TO ix_yaml_templates_curriculum_folder_node_id;
                    END IF;
                END $$;
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE yaml_templates
                DROP CONSTRAINT IF EXISTS uq_yaml_templates_curriculum_folder_node_id
                """
            )
        )

        has_yaml_folder_fk = conn.execute(
            text(
                """
                SELECT 1
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                WHERE t.relname = 'yaml_templates'
                  AND c.contype = 'f'
                  AND pg_get_constraintdef(c.oid) LIKE '%curriculum_folder_node_id%'
                  AND pg_get_constraintdef(c.oid) LIKE '%REFERENCES curriculum_folder_nodes%'
                LIMIT 1
                """
            )
        ).first()

        if has_yaml_folder_fk is None:
            conn.execute(
                text(
                    """
                    ALTER TABLE yaml_templates
                    ADD CONSTRAINT yaml_templates_curriculum_folder_node_id_fkey
                    FOREIGN KEY (curriculum_folder_node_id)
                    REFERENCES curriculum_folder_nodes(id)
                    ON DELETE CASCADE
                    """
                )
            )
