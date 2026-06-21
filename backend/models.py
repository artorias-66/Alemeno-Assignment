from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, JSON, Date
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from database import Base

def generate_uuid():
    return str(uuid.uuid4())

class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    filename = Column(String, nullable=False)
    status = Column(String, default="pending")  # pending, processing, completed, failed
    row_count_raw = Column(Integer, nullable=True)
    row_count_clean = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    transactions = relationship("Transaction", back_populates="job")
    summary = relationship("JobSummary", uselist=False, back_populates="job")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String, primary_key=True, default=generate_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    txn_id = Column(String, nullable=True)
    date = Column(Date, nullable=True)
    merchant = Column(String, nullable=True)
    amount = Column(Float, nullable=True)
    currency = Column(String, nullable=True)
    status = Column(String, nullable=True)
    category = Column(String, nullable=True)
    account_id = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    
    is_anomaly = Column(Boolean, default=False)
    anomaly_reason = Column(String, nullable=True)
    llm_category = Column(String, nullable=True)
    llm_failed = Column(Boolean, default=False)

    job = relationship("Job", back_populates="transactions")

class JobSummary(Base):
    __tablename__ = "job_summaries"

    id = Column(String, primary_key=True, default=generate_uuid)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    total_spend_inr = Column(Float, nullable=True)
    total_spend_usd = Column(Float, nullable=True)
    top_merchants = Column(JSON, nullable=True)
    anomaly_count = Column(Integer, nullable=True)
    narrative = Column(Text, nullable=True)
    risk_level = Column(String, nullable=True)
    per_category_spend = Column(JSON, nullable=True)  # {category: {INR: float, USD: float}}

    job = relationship("Job", back_populates="summary")
