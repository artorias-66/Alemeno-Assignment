import json
import time
import logging
from typing import List, Dict, Any

from groq import Groq
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_client():
    api_key = settings.GROQ_API_KEY
    if not api_key:
        logger.warning("GROQ_API_KEY is not set. LLM features will fail.")
        return None
    return Groq(api_key=api_key)


def retry_with_backoff(func, max_retries=3, base_delay=2):
    """Retries a function with exponential backoff."""
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"Max retries reached. Error: {str(e)}")
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"LLM call failed: {str(e)}. Retrying in {delay}s...")
            time.sleep(delay)


def classify_transactions_batch(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Classifies a batch of transactions using the LLM.

    Each transaction must have an 'id' key (a synthetic index set by the caller).
    Returns the same list with 'llm_category' and 'llm_failed' fields added.
    Allowed categories: Food, Shopping, Travel, Transport, Utilities,
    Cash Withdrawal, Entertainment, Other.
    """
    client = get_client()
    if not client:
        for t in transactions:
            t['llm_failed'] = True
        return transactions

    # Send only the minimum tokens needed for classification
    batch_data = [
        {"id": t.get('id'), "merchant": t.get('merchant'), "notes": t.get('notes')}
        for t in transactions
    ]

    prompt = (
        "Classify the following transactions into one of these exact categories: "
        "Food, Shopping, Travel, Transport, Utilities, Cash Withdrawal, Entertainment, Other.\n"
        "Output a JSON object with a single key 'classifications' containing an array of objects. "
        "Each object must have 'id' (matching the input) and 'category'.\n\n"
        "Transactions:\n"
    )
    prompt += json.dumps(batch_data)

    def _call_llm():
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a transaction classification API. Return ONLY valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

    try:
        result_text = retry_with_backoff(_call_llm)
        parsed = json.loads(result_text)
        classifications = parsed.get("classifications", [])

        # Map results back by id
        cat_map = {
            str(item.get('id')): item.get('category')
            for item in classifications
            if isinstance(item, dict)
        }

        returned_ids = set(cat_map.keys())
        for t in transactions:
            txn_id_str = str(t.get('id'))
            if txn_id_str in returned_ids:
                t['llm_category'] = cat_map[txn_id_str]
                t['llm_failed'] = False
            else:
                # LLM dropped this id — mark failed without crashing
                logger.warning(f"LLM did not return classification for id={txn_id_str}")
                t['llm_failed'] = True

    except Exception as e:
        logger.error(f"Batch classification failed completely: {str(e)}")
        for t in transactions:
            t['llm_failed'] = True

    return transactions


def generate_narrative_summary(
    pre_computed: Dict[str, Any]
) -> Dict[str, Any]:
    """Generates only the narrative and risk_level from the LLM.

    All numeric aggregates (totals, top merchants, anomaly count) must be
    computed by the caller in Pandas and passed in via ``pre_computed``.
    This keeps the LLM responsible for language, not arithmetic.

    Args:
        pre_computed: Dict with keys:
            - total_spend_inr (float)
            - total_spend_usd (float)
            - top_merchants (dict[str, float])
            - anomaly_count (int)
            - sample_transactions (list of dicts for context)

    Returns:
        Dict with 'narrative' (str) and 'risk_level' ('low'|'medium'|'high'),
        or empty dict on failure.
    """
    client = get_client()
    if not client:
        return {}

    context = {
        "total_spend_inr": pre_computed.get("total_spend_inr"),
        "total_spend_usd": pre_computed.get("total_spend_usd"),
        "top_merchants": pre_computed.get("top_merchants"),
        "anomaly_count": pre_computed.get("anomaly_count"),
        "sample_transactions": pre_computed.get("sample_transactions", [])
    }

    prompt = (
        "You are a financial analyst writing a brief summary for an internal report.\n"
        "Based on the pre-computed statistics below, return a JSON object with exactly two keys:\n"
        "  'narrative': a 2-3 sentence plain-English summary of the spending habits and any risk signals.\n"
        "  'risk_level': exactly one of 'low', 'medium', or 'high'.\n\n"
        "Do NOT recalculate or change any numbers — they are already correct.\n\n"
        "Statistics:\n"
    )
    prompt += json.dumps(context)

    def _call_llm():
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a financial analysis API. Return ONLY valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

    try:
        result_text = retry_with_backoff(_call_llm)
        parsed = json.loads(result_text)
        return {
            "narrative": parsed.get("narrative", ""),
            "risk_level": parsed.get("risk_level", "low"),
        }
    except Exception as e:
        logger.error(f"Summary generation failed: {str(e)}")
        return {}
