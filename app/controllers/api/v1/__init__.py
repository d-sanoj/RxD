"""Version 1 of the REST API. Mounted under /api/v1 by app.main."""

from fastapi import APIRouter

from app.controllers.api.v1 import admin, audit, auth, chat, documents, intakes, patients, rules, suggestions

api_v1_router = APIRouter()
for _module in (auth, patients, intakes, documents, chat, suggestions, rules, audit, admin):
    api_v1_router.include_router(_module.router)
