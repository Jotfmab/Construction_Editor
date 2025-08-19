from __future__ import annotations
from pydantic import BaseModel
from typing import Optional, List

class BulkCell(BaseModel):
    row_id: int
    day: int
    task: Optional[str] = None
    hours: Optional[float] = None
    labor_code: Optional[str] = None

class BulkPayload(BaseModel):
    records: List[BulkCell]
