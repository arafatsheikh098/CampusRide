"""Telegram linking and webhook. Implemented in M8."""
from fastapi import APIRouter

router = APIRouter(prefix="/telegram", tags=["telegram"])
