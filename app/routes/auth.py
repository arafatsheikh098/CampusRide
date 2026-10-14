"""Auth routes (sign-up, sign-in, sign-out, recovery). Implemented in M2."""
from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])
