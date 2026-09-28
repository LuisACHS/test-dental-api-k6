from fastapi import APIRouter

from app.api.v1 import appointments, auth, dentists, patients

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(dentists.router)
api_router.include_router(patients.router)
api_router.include_router(appointments.router)
