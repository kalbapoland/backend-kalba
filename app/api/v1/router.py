from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.tags import router as tags_router
from app.api.v1.users import router as users_router
from app.api.v1.video import router as video_router
from app.api.v1.workshops import router as workshops_router

router = APIRouter(prefix="/api/v1")

router.include_router(auth_router)
router.include_router(users_router)
router.include_router(notifications_router)
router.include_router(workshops_router)
router.include_router(video_router)
router.include_router(tags_router)
