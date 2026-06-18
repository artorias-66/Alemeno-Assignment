import os
import json
from datetime import datetime
import pandas as pd
from sqlalchemy.orm import Session

from celery_app import celery
from database import SessionLocal
from models import Job, Transaction, JobSummary
from utils import clean_data, detect_anomalies
from llm import classify_transactions_batch, generate_narrative_summary

BATCH_SIZE = 20

@celery.task(bind=True)
def process_transactions_csv(self, job_id: str, file_path: str):
    db: Session = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()
    
    if not job:
        db.close()
        return f"Job {job_id} not found."
    
    try:
        job.status = "processing"
        db.commit()

        # Step 1: Data Cleaning
        df = clean_data(file_path)
        job.row_count_raw = len(pd.read_csv(file_path))
        job.row_count_clean = len(df)
        
        # Step 2: Anomaly Detection
        df = detect_anomalies(df)

        transactions_data = df.to_dict('records')
        
        # Step 3: LLM Classification (Batching)
        uncategorized = [t for t in transactions_data if t.get('category') == 'Uncategorised']
        
        # We need a temporary id to map back results
        for idx, t in enumerate(uncategorized):
            t['id'] = str(idx)
            
        categorized_results = []
        for i in range(0, len(uncategorized), BATCH_SIZE):
            batch = uncategorized[i:i+BATCH_SIZE]
            processed_batch = classify_transactions_batch(batch)
            categorized_results.extend(processed_batch)
            
        # Merge back
        cat_map = {t['id']: t for t in categorized_results if 'id' in t}
        for t in transactions_data:
            if t.get('category') == 'Uncategorised':
                # find map
                # for simple mapping, we search by original values but adding a custom 'temp_id' is safer.
                # Since we already mutated the dictionaries in the list directly (pass by reference in python),
                # transactions_data elements should already be updated with 'llm_category' and 'llm_failed'.
                pass
                
        # Insert Transactions into DB
        db_transactions = []
        for t in transactions_data:
            txn = Transaction(
                job_id=job.id,
                txn_id=t.get('txn_id'),
                date=t.get('date'),
                merchant=t.get('merchant'),
                amount=t.get('amount'),
                currency=t.get('currency'),
                status=t.get('status'),
                category=t.get('category'),
                account_id=t.get('account_id'),
                notes=t.get('notes'),
                is_anomaly=t.get('is_anomaly', False),
                anomaly_reason=t.get('anomaly_reason'),
                llm_category=t.get('llm_category'),
                llm_raw_response=t.get('llm_raw_response'),
                llm_failed=t.get('llm_failed', False)
            )
            db_transactions.append(txn)
            
        db.bulk_save_objects(db_transactions)
        db.commit()

        # Step 4: LLM Narrative Summary
        # Prepare data for summary
        summary_data = generate_narrative_summary(transactions_data)
        
        if summary_data:
            job_summary = JobSummary(
                job_id=job.id,
                total_spend_inr=summary_data.get('total_spend_inr'),
                total_spend_usd=summary_data.get('total_spend_usd'),
                top_merchants=summary_data.get('top_merchants'),
                anomaly_count=summary_data.get('anomaly_count'),
                narrative=summary_data.get('narrative'),
                risk_level=summary_data.get('risk_level')
            )
            db.add(job_summary)

        # Mark job as completed
        job.status = "completed"
        job.completed_at = datetime.utcnow()
        db.commit()
        
    except Exception as e:
        db.rollback()
        job.status = "failed"
        job.error_message = str(e)
        job.completed_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()
        
    return f"Job {job_id} processing finished."
