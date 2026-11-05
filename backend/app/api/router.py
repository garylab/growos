from fastapi import APIRouter

from fastapi import Depends

from app.api.deps import get_principal
from app.api.routes import (actions, auth, brand, content, geo, health, integrations, jobs, notifications, overview,
                            plan, projects, scorecard, seo, usage)

api_router = APIRouter(prefix="/api")
# Public: health probes, the login endpoint, and the Google OAuth callback (a browser redirect carries no session;
# it is protected by the single-use state token instead).
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(integrations.public_router)
# Everything else requires a signed-in user or the system token.
for r in (projects, integrations, jobs, seo, geo, brand, actions, overview, plan, content, scorecard, notifications, usage):
    api_router.include_router(r.router, dependencies=[Depends(get_principal)])
