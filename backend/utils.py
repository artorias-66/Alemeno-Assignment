import pandas as pd
import numpy as np
from typing import Tuple
from config import settings

DOMESTIC_BRANDS = settings.DOMESTIC_BRANDS

def clean_data(file_path: str) -> Tuple[pd.DataFrame, int]:
    """Reads, normalises, and deduplicates a transaction CSV.

    Returns:
        A tuple of (cleaned DataFrame, raw row count before dedup).
    """
    df = pd.read_csv(file_path)
    raw_count = len(df)

    # Standardize column names
    df.columns = [col.strip().lower() for col in df.columns]

    # Ensure required columns exist
    expected_cols = ["txn_id", "date", "merchant", "amount", "currency", "status", "category", "account_id", "notes"]
    for col in expected_cols:
        if col not in df.columns:
            df[col] = None

    # ── Normalise BEFORE dedup so format differences don't hide logical dupes ──

    # Normalise dates to ISO 8601 (handles DD-MM-YYYY and YYYY/MM/DD)
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], format='mixed', dayfirst=True, errors='coerce').dt.date

    # Strip currency symbols and convert amount to numeric
    if 'amount' in df.columns:
        df['amount'] = df['amount'].astype(str).str.replace(r'[^\d.]', '', regex=True)
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce')

    # Uppercase status for consistency
    if 'status' in df.columns:
        df['status'] = df['status'].astype(str).str.upper().str.strip()
        df['status'] = df['status'].replace('NAN', None)

    # Uppercase currency for consistency
    if 'currency' in df.columns:
        df['currency'] = df['currency'].astype(str).str.upper().str.strip()
        df['currency'] = df['currency'].replace('NAN', None)

    # Fill missing categories
    if 'category' in df.columns:
        df['category'] = df['category'].fillna('Uncategorised')
        df['category'] = df['category'].replace('nan', 'Uncategorised')

    # Dedup on business key (date + merchant + amount + currency + account_id)
    # This removes logical duplicates that differ only in notes/txn_id/row order
    business_key = [c for c in ['date', 'merchant', 'amount', 'currency', 'account_id'] if c in df.columns]
    if business_key:
        df = df.drop_duplicates(subset=business_key)
    else:
        df = df.drop_duplicates()

    # Replace NaN with None for DB insertion
    df = df.replace({np.nan: None})
    return df, raw_count

def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detects anomalous transactions using vectorized Pandas operations.
    Rules:
    1. Amount > 3x the account's median amount.
    2. Currency is USD but merchant is a domestic brand.

    Args:
        df (pd.DataFrame): Cleaned transactions DataFrame.

    Returns:
        pd.DataFrame: DataFrame with 'is_anomaly' and 'anomaly_reason' columns.
    """
    df['is_anomaly'] = False
    df['anomaly_reason'] = None

    if df.empty:
        return df

    # 1. Flag amount > 3x the account's median
    if 'account_id' in df.columns and 'amount' in df.columns:
        medians = df.groupby('account_id')['amount'].transform('median')
        amount_mask = (df['amount'] > 3 * medians) & (medians > 0)
        
        df.loc[amount_mask, 'is_anomaly'] = True
        df.loc[amount_mask, 'anomaly_reason'] = (
            "Amount " + df.loc[amount_mask, 'amount'].astype(str) + 
            " is > 3x account median " + medians[amount_mask].astype(str)
        )

    # 2. Flag USD currency for domestic-only brand
    if 'currency' in df.columns and 'merchant' in df.columns:
        usd_mask = df['currency'] == 'USD'
        merchant_str = df['merchant'].fillna('').astype(str).str.lower()
        
        pattern = '|'.join(r'\b' + brand + r'\b' for brand in settings.DOMESTIC_BRANDS)
        domestic_mask = merchant_str.str.contains(pattern, regex=True, na=False)
        
        currency_mask = usd_mask & domestic_mask
        
        df.loc[currency_mask, 'is_anomaly'] = True
        
        # Append reason safely
        new_reason = "USD currency used for domestic brand"
        existing_reasons = df.loc[currency_mask, 'anomaly_reason']
        df.loc[currency_mask, 'anomaly_reason'] = np.where(
            existing_reasons.isnull(),
            new_reason,
            existing_reasons.astype(str) + "; " + new_reason
        )

    return df
