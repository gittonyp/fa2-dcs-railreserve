from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class ResetRequest(BaseModel):
    train_id: str = "12951"
    journey_date: date
    seat_count: int = Field(default=50, ge=1, le=500)


class HoldRequest(BaseModel):
    train_id: str = "12951"
    journey_date: date
    seat_no: str
    user_id: str


class PayRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)
    amount: Decimal = Field(gt=0)
