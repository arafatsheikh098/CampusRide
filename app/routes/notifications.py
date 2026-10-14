"""In-app notifications. Implemented in M8."""
from fastapi import APIRouter

router = APIRouter(prefix="/notifications", tags=["notifications"])
