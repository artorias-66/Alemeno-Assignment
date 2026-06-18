import os
import json
import time
import logging
from typing import List, Dict, Any
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize the Groq client
# Requires GROQ_API_KEY environment variable
def get_client():
    api_key = os.getenv("GROQ_API_KEY")
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
            logger.warning(f"LLM call failed: {str(e)}. Retrying in {delay} seconds...")
            time.sleep(delay)

def classify_transactions_batch(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Takes a batch of transactions and returns them with an added 'llm_category' field.
    Allowed categories: Food, Shopping, Travel, Transport, Utilities, Cash Withdrawal, Entertainment, Other.
    """
    client = get_client()
    if not client:
        for t in transactions:
            t['llm_failed'] = True
        return transactions

    prompt = (
        "Classify the following transactions into one of these exact categories: "
        "Food, Shopping, Travel, Transport, Utilities, Cash Withdrawal, Entertainment, Other.\n"
        "Return the result as a strict JSON array of objects with keys 'txn_id' and 'category'.\n\n"
        "Transactions:\n"
    )
    
    # Send minimal data to save tokens
    batch_data = [{"txn_id": t.get('id'), "merchant": t.get('merchant'), "notes": t.get('notes')} for t in transactions]
    prompt += json.dumps(batch_data)

    def _call_llm():
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a transaction classification assistant. Output ONLY valid JSON array."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        # We need to ensure it's a JSON array format
        # Actually response_format={"type": "json_object"} forces a JSON object.
        # We'll adjust prompt to ask for an object containing the array.
        pass

    # Let's adjust the nested function slightly to handle the JSON object requirement of Groq.
    prompt = (
        "Classify the following transactions into one of these exact categories: "
        "Food, Shopping, Travel, Transport, Utilities, Cash Withdrawal, Entertainment, Other.\n"
        "Output a JSON object with a single key 'classifications' which contains an array of objects. "
        "Each object must have 'txn_id' and 'category'.\n\n"
        "Transactions:\n"
    )
    prompt += json.dumps(batch_data)

    def _call_llm_fixed():
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "You are a transaction classification API. You must return ONLY valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        return response.choices[0].message.content

    try:
        result_text = retry_with_backoff(_call_llm_fixed)
        parsed = json.loads(result_text)
        classifications = parsed.get("classifications", [])
        
        # Map back to original transactions
        cat_map = {str(item.get('txn_id')): item.get('category') for item in classifications if isinstance(item, dict)}
        
        for t in transactions:
            txn_id_str = str(t.get('id'))
            if txn_id_str in cat_map:
                t['llm_category'] = cat_map[txn_id_str]
                t['llm_failed'] = False
                t['llm_raw_response'] = result_text
            else:
                t['llm_failed'] = True
                
    except Exception as e:
        logger.error(f"Batch classification failed completely: {str(e)}")
        for t in transactions:
            t['llm_failed'] = True

    return transactions

def generate_narrative_summary(transactions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generates a narrative summary based on all processed transactions.
    Output requires: total spend by currency, top 3 merchants, anomaly count, 2-3 sentence narrative, risk_level.
    """
    client = get_client()
    if not client:
        return {}

    prompt = (
        "You are a financial analyst. Analyze these transactions and generate a JSON summary.\n"
        "The JSON object must have these exact keys:\n"
        "- 'total_spend_inr' (number)\n"
        "- 'total_spend_usd' (number)\n"
        "- 'top_merchants' (object with merchant name as key and total amount as value, top 3 only)\n"
        "- 'anomaly_count' (number, total transactions flagged as anomaly)\n"
        "- 'narrative' (string, 2-3 sentences summarizing spending habits)\n"
        "- 'risk_level' (string, exactly one of: 'low', 'medium', 'high')\n\n"
        "Transactions data:\n"
    )
    
    simplified = []
    for t in transactions:
        simplified.append({
            "merchant": t.get('merchant'),
            "amount": t.get('amount'),
            "currency": t.get('currency'),
            "is_anomaly": t.get('is_anomaly', False)
        })
        
    prompt += json.dumps(simplified)

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
        return json.loads(result_text)
    except Exception as e:
        logger.error(f"Summary generation failed: {str(e)}")
        return {}
