import logging
from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from celery_app import celery
from database import SessionLocal
from models import Job, Transaction, JobSummary
from utils import clean_data, detect_anomalies, compute_aggregates
from llm import classify_transactions_batch, generate_narrative_summary
from config import settings

BATCH_SIZE = settings.BATCH_SIZE

logger = logging.getLogger(__name__)



@celery.task(bind=True)
def process_transactions_csv(self, job_id: str, file_path: str):
    """Celery background task to process an uploaded CSV file.

    Steps:
      1. Clean data (normalize, dedup).
      2. Detect anomalies.
      3. LLM-classify uncategorized transactions (batched, failure-isolated per batch).
      4. Persist transactions.
      5. Compute aggregates in Pandas; ask LLM only for narrative + risk_level.
      6. Persist summary (failure here degrades gracefully — job still completes).
    """
    db: Session = SessionLocal()
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        db.close()
        logger.error(f"Job {job_id} not found in database.")
        return f"Job {job_id} not found."

    try:
        job.status = "processing"
        db.commit()

        # ── Step 1: Data Cleaning ──────────────────────────────────────────────
        logger.info(f"Job {job_id}: Starting data cleaning on {file_path}")
        df, raw_count = clean_data(file_path)          # raw_count avoids a 2nd pd.read_csv
        job.row_count_raw = raw_count
        job.row_count_clean = len(df)

        logger.info(
            f"Job {job_id}: Cleaning done. "
            f"Raw={job.row_count_raw}, Clean={job.row_count_clean}. "
            "Starting anomaly detection."
        )

        # ── Step 2: Anomaly Detection ──────────────────────────────────────────
        df = detect_anomalies(df)

        transactions_data = df.to_dict('records')

        # ── Step 3: LLM Classification ─────────────────────────────────────────
        uncategorized = [t for t in transactions_data if t.get('category') == 'Uncategorised']
        logger.info(f"Job {job_id}: {len(uncategorized)} uncategorized transactions.")

        # Assign synthetic ids so we can map results back reliably
        for idx, t in enumerate(uncategorized):
            t['_llm_id'] = str(idx)

        for t in uncategorized:
            t['id'] = t['_llm_id']         # llm function uses 'id'

        for i in range(0, len(uncategorized), BATCH_SIZE):
            batch = uncategorized[i:i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (len(uncategorized) + BATCH_SIZE - 1) // BATCH_SIZE
            logger.info(f"Job {job_id}: LLM batch {batch_num}/{total_batches}")
            classify_transactions_batch(batch)          # mutates in-place

        # Merge llm_category back into main list
        llm_map = {t['_llm_id']: t for t in uncategorized}
        for t in transactions_data:
            llm_id = t.get('_llm_id')
            if llm_id and llm_id in llm_map:
                llm_result = llm_map[llm_id]
                t['llm_category'] = llm_result.get('llm_category')
                t['llm_failed'] = llm_result.get('llm_failed', False)
                if t['llm_category']:
                    t['category'] = t['llm_category']

        logger.info(f"Job {job_id}: Saving {len(transactions_data)} transactions.")

        # ── Step 4: Persist Transactions ───────────────────────────────────────
        db_transactions = [
            Transaction(
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
                llm_failed=t.get('llm_failed', False),
            )
            for t in transactions_data
        ]
        db.bulk_save_objects(db_transactions)
        db.commit()

        # ── Step 5: Compute Aggregates in Pandas ───────────────────────────────
        # Re-read the category column from the mutated transactions_data so it
        # reflects any LLM overwrites before we compute aggregates.
        agg_df = pd.DataFrame(transactions_data)
        aggregates = compute_aggregates(agg_df)

        # ── Step 6: LLM Narrative (isolated — never fails the job) ─────────────
        logger.info(f"Job {job_id}: Generating narrative summary.")
        try:
            sample = [
                {"merchant": t.get('merchant'), "amount": t.get('amount'),
                 "currency": t.get('currency'), "is_anomaly": t.get('is_anomaly', False)}
                for t in transactions_data[:20]           # send a sample, not all rows
            ]
            llm_result = generate_narrative_summary({**aggregates, "sample_transactions": sample})
            narrative = llm_result.get("narrative", "")
            risk_level = llm_result.get("risk_level", "low")
        except Exception as e:
            logger.error(f"Job {job_id}: Narrative generation failed (non-fatal): {e}", exc_info=True)
            narrative = None
            risk_level = None

        job_summary = JobSummary(
            job_id=job.id,
            total_spend_inr=aggregates["total_spend_inr"],
            total_spend_usd=aggregates["total_spend_usd"],
            top_merchants=aggregates["top_merchants"],
            anomaly_count=aggregates["anomaly_count"],
            per_category_spend=aggregates["per_category_spend"],
            narrative=narrative,
            risk_level=risk_level,
        )
        db.add(job_summary)

        job.status = "completed"
        job.completed_at = datetime.utcnow()
        db.commit()
        logger.info(f"Job {job_id}: Successfully completed.")

    except Exception as e:
        db.rollback()
        logger.error(f"Job {job_id}: Fatal error: {e}", exc_info=True)
        job.status = "failed"
        job.error_message = str(e)
        job.completed_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()

    return f"Job {job_id} processing finished."
