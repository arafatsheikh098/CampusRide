"""Trusted-contact read-only page. Implemented in M7."""
from fastapi import APIRouter

router = APIRouter(prefix="/trusted", tags=["trusted_contact"])
