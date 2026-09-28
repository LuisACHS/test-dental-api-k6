"""Importar todos los modelos aqui para que Alembic los vea en el metadata."""

from app.models.appointment import Appointment, AppointmentStatus
from app.models.dentist import Dentist
from app.models.user import User, UserRole

__all__ = ["Appointment", "AppointmentStatus", "Dentist", "User", "UserRole"]
