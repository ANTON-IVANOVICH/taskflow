from fastapi import APIRouter

from app.api.v1 import auth, integrations, system, tasks, teams, users

api_v1_router = APIRouter()
api_v1_router.include_router(users.router)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(integrations.router)
api_v1_router.include_router(tasks.router)
api_v1_router.include_router(teams.router)
api_v1_router.include_router(system.router)
