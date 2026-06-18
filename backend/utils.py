import pandas as pd
import numpy as np

DOMESTIC_BRANDS = ["swiggy", "ola", "irctc", "zomato", "paytm", "bms", "bookmyshow"]

def clean_data(file_path: str) -> pd.DataFrame:
    # Read CSV
    df = pd.read_csv(file_path)
    
    # Standardize column names if needed, assume they are mostly correct based on assignment
    df.columns = [col.strip().lower() for col in df.columns]
    
    # Ensure required columns exist
    expected_cols = ["txn_id", "date", "merchant", "amount", "currency", "status", "category", "account_id", "notes"]
    for col in expected_cols:
        if col not in df.columns:
            df[col] = None

    # Remove exact duplicate rows
    df = df.drop_duplicates()

    # Normalise dates to ISO 8601
    # Mixed formats: DD-MM-YYYY and YYYY/MM/DD both appear
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date'], format='mixed', dayfirst=True, errors='coerce').dt.date

    # Strip currency symbols from amounts and convert to numeric
    if 'amount' in df.columns:
        df['amount'] = df['amount'].astype(str).str.replace(r'[^\d.]', '', regex=True)
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce')

    # Uppercase status values
    if 'status' in df.columns:
        df['status'] = df['status'].astype(str).str.upper().str.strip()
        df['status'] = df['status'].replace('NAN', None)

    # Uppercase currency for consistency
    if 'currency' in df.columns:
        df['currency'] = df['currency'].astype(str).str.upper().str.strip()
        df['currency'] = df['currency'].replace('NAN', None)

    # Fill missing categories with 'Uncategorised'
    if 'category' in df.columns:
        df['category'] = df['category'].fillna('Uncategorised')
        df['category'] = df['category'].replace('nan', 'Uncategorised')

    # Ensure NaN values are None for DB insertion
    df = df.replace({np.nan: None})
    return df

def detect_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    df['is_anomaly'] = False
    df['anomaly_reason'] = None

    # 1. Flag amount > 3x the account's median
    account_medians = df.groupby('account_id')['amount'].median()
    
    for idx, row in df.iterrows():
        account_id = row['account_id']
        amount = row['amount']
        merchant = str(row['merchant']).lower() if row['merchant'] else ""
        currency = row['currency']
        
        is_anomaly = False
        reasons = []

        if account_id in account_medians and pd.notnull(amount):
            median = account_medians[account_id]
            if median > 0 and amount > 3 * median:
                is_anomaly = True
                reasons.append(f"Amount {amount} is > 3x account median {median}")

        # 2. Flag USD currency for domestic-only brand
        if currency == "USD":
            for brand in DOMESTIC_BRANDS:
                if brand in merchant:
                    is_anomaly = True
                    reasons.append(f"USD currency used for domestic brand {brand}")
                    break
        
        if is_anomaly:
            df.at[idx, 'is_anomaly'] = True
            df.at[idx, 'anomaly_reason'] = "; ".join(reasons)

    return df
