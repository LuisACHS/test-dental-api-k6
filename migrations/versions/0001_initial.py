"""Esquema inicial: users, dentists, appointments + EXCLUDE anti-solape.

Revision ID: 0001
Revises:
Create Date: 2026-09-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NO_OVERLAP_CONSTRAINT = "appointments_no_overlap"


def upgrade() -> None:
    #  Necesaria para poder mezclar '=' sobre un uuid con '&&' sobre un rango
    #  dentro del mismo indice GiST.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=128), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "dentists",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("specialty", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dentists"),
    )

    op.create_table(
        "appointments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dentist_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_appointments"),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["users.id"], name="fk_appointments_patient_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["dentist_id"], ["dentists.id"], name="fk_appointments_dentist_id_dentists", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("starts_at < ends_at", name="ck_appointments_valid_range"),
    )
    op.create_index("ix_appointments_dentist_id_starts_at", "appointments", ["dentist_id", "starts_at"])
    op.create_index("ix_appointments_patient_id_starts_at", "appointments", ["patient_id", "starts_at"])

    #  El corazon del asunto: dos citas del mismo dentista no pueden solaparse.
    #  Se resuelve en el motor y no con un SELECT previo en Python, que bajo
    #  concurrencia deja una ventana de carrera y produce dobles reservas.
    #  El rango es '[)': una cita 14:00-14:30 y otra 14:30-15:00 no chocan.
    op.execute(
        f"""
        ALTER TABLE appointments
        ADD CONSTRAINT {NO_OVERLAP_CONSTRAINT}
        EXCLUDE USING gist (
            dentist_id WITH =,
            tstzrange(starts_at, ends_at, '[)') WITH &&
        ) WHERE (status <> 'cancelled')
        """
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE appointments DROP CONSTRAINT IF EXISTS {NO_OVERLAP_CONSTRAINT}")
    op.drop_index("ix_appointments_patient_id_starts_at", table_name="appointments")
    op.drop_index("ix_appointments_dentist_id_starts_at", table_name="appointments")
    op.drop_table("appointments")
    op.drop_table("dentists")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
