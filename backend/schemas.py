from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
import datetime

class JobResponse(BaseModel):
    job_id: str

class JobSummarySchema(BaseModel):
    total_spend_inr: Optional[float] = None
    total_spend_usd: Optional[float] = None
    top_merchants: Optional[Dict[str, float]] = None
    anomaly_count: Optional[int] = None
    narrative: Optional[str] = None
    risk_level: Optional[str] = None

class JobStatusResponse(BaseModel):
    status: str
    summary: Optional[JobSummarySchema] = None

class TransactionSchema(BaseModel):
    txn_id: Optional[str] = None
    date: Optional[datetime.date] = None
    merchant: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    category: Optional[str] = None
    account_id: Optional[str] = None
    is_anomaly: bool
    anomaly_reason: Optional[str] = None
    llm_category: Optional[str] = None
    llm_raw_response: Optional[str] = None
    llm_failed: bool

class JobResultResponse(BaseModel):
    cleaned_transactions: List[TransactionSchema]
    anomalies: List[TransactionSchema]
    per_category_spend: Dict[str, float]
    summary: Optional[JobSummarySchema] = None

class JobListResponse(BaseModel):
    id: str
    filename: str
    status: str
    row_count_raw: Optional[int] = None
    created_at: datetime.datetime

    class Config:
        from_attributes = True
