"""Moderator queues and actions. Implemented in M2/M3/M7."""
from fastapi import APIRouter

router = APIRouter(prefix="/moderation", tags=["moderation"])
