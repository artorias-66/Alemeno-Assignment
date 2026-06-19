import os
import shutil
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager

from database import engine, Base, get_db
from models import Job, Transaction, JobSummary
from schemas import JobResponse, JobStatusResponse, JobResultResponse, JobListResponse, JobSummarySchema, TransactionSchema
from tasks import process_transactions_csv
import logging
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    Base.metadata.create_all(bind=engine)
    yield

app = FastAPI(title="AI-Powered Transaction Processing Pipeline", lifespan=lifespan)

@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error occurred. Please check logs."})

UPLOAD_DIR = "/app/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/jobs/upload", response_model=JobResponse)
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Uploads a CSV file of transactions, saves it, and enqueues a background job to process it.
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")
    
    # Save the file locally
    file_location = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Create Job record
    job = Job(filename=file.filename, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    
    # Enqueue processing task
    process_transactions_csv.delay(job.id, file_location)
    
    return {"job_id": job.id}

@app.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """
    Retrieves the current status of a background job. If completed, includes the generated summary.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    response = {"status": job.status}
    
    if job.status == "completed" and job.summary:
        response["summary"] = {
            "total_spend_inr": job.summary.total_spend_inr,
            "total_spend_usd": job.summary.total_spend_usd,
            "top_merchants": job.summary.top_merchants,
            "anomaly_count": job.summary.anomaly_count,
            "narrative": job.summary.narrative,
            "risk_level": job.summary.risk_level
        }
        
    return response

@app.get("/jobs/{job_id}/results", response_model=JobResultResponse)
def get_job_results(job_id: str, db: Session = Depends(get_db)):
    """
    Retrieves the full processing results for a completed job, including all cleaned transactions, anomalies, and summary.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job processing is not completed yet.")
        
    transactions = db.query(Transaction).filter(Transaction.job_id == job_id).all()
    cleaned_txns = []
    anomalies = []
    per_category_spend = {}
    
    for t in transactions:
        txn_schema = TransactionSchema(
            txn_id=t.txn_id,
            date=t.date,
            merchant=t.merchant,
            amount=t.amount,
            currency=t.currency,
            status=t.status,
            category=t.category,
            account_id=t.account_id,
            is_anomaly=t.is_anomaly,
            anomaly_reason=t.anomaly_reason,
            llm_category=t.llm_category,
            llm_raw_response=t.llm_raw_response,
            llm_failed=t.llm_failed
        )
        cleaned_txns.append(txn_schema)
        
        if t.is_anomaly:
            anomalies.append(txn_schema)
            
        # Per-category spend logic
        cat = t.llm_category if t.llm_category else t.category
        cat = cat if cat else "Uncategorised"
        amount = t.amount if t.amount else 0.0
        # Simplification: we'll just sum raw amounts without currency conversion for this category spend breakdown,
        # or we could split by currency. The assignment doesn't specify, so we sum raw numbers.
        if cat not in per_category_spend:
            per_category_spend[cat] = 0.0
        per_category_spend[cat] += amount

    response = {
        "cleaned_transactions": cleaned_txns,
        "anomalies": anomalies,
        "per_category_spend": per_category_spend
    }
    
    if job.summary:
        response["summary"] = {
            "total_spend_inr": job.summary.total_spend_inr,
            "total_spend_usd": job.summary.total_spend_usd,
            "top_merchants": job.summary.top_merchants,
            "anomaly_count": job.summary.anomaly_count,
            "narrative": job.summary.narrative,
            "risk_level": job.summary.risk_level
        }
        
    return response

@app.get("/jobs", response_model=List[JobListResponse])
def list_jobs(status: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Lists all jobs, optionally filtering by status (e.g., 'pending', 'completed').
    """
    query = db.query(Job)
    if status:
        query = query.filter(Job.status == status)
    jobs = query.order_by(Job.created_at.desc()).all()
    return jobs
