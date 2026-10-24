from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class DeviceCreate(BaseModel):
    device_type_id: int
    manufacturer: str = Field(min_length=1)
    model: str = Field(min_length=1)
    device_name: str = Field(min_length=1)
    net_price: Decimal = Field(ge=0)
    serial_number: str = Field(min_length=1)
    status: str = Field(min_length=1)


class AssignmentCreate(BaseModel):
    device_id: int
    person_id: int
    issued_at: date | None = None


class AssignmentReturn(BaseModel):
    returned_at: date | None = None
