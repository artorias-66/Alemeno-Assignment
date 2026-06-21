"""
Unit tests for clean_data, detect_anomalies, and _compute_aggregates.

Run with:
    cd backend && python -m pytest tests/ -v
"""

import io
import textwrap
import pytest
import pandas as pd
import numpy as np

# ── Helpers ────────────────────────────────────────────────────────────────────

def _csv_to_file(csv_text: str, tmp_path):
    """Write a CSV string to a temp file and return its path."""
    p = tmp_path / "test.csv"
    p.write_text(textwrap.dedent(csv_text).strip())
    return str(p)


# ── clean_data ─────────────────────────────────────────────────────────────────

from utils import clean_data


class TestCleanData:
    def test_returns_tuple_with_raw_count(self, tmp_path):
        csv = """
        txn_id,date,merchant,amount,currency,status,category,account_id,notes
        T1,04-09-2024,Swiggy,₹250,INR,success,Food,ACC1,lunch
        T2,2024/09/05,Zomato,$100,USD,Success,Food,ACC1,dinner
        """
        df, raw_count = clean_data(_csv_to_file(csv, tmp_path))
        assert raw_count == 2
        assert len(df) == 2

    def test_normalizes_dates_mixed_formats(self, tmp_path):
        csv = """
        txn_id,date,merchant,amount,currency,status,category,account_id,notes
        T1,04-09-2024,Swiggy,250,INR,success,Food,ACC1,
        T2,2024/09/05,Zomato,100,USD,success,Food,ACC1,
        """
        df, _ = clean_data(_csv_to_file(csv, tmp_path))
        import datetime
        assert df['date'].iloc[0] == datetime.date(2024, 9, 4)
        assert df['date'].iloc[1] == datetime.date(2024, 9, 5)

    def test_strips_currency_symbols_from_amounts(self, tmp_path):
        csv = """
        txn_id,date,merchant,amount,currency,status,category,account_id,notes
        T1,04-09-2024,Swiggy,₹1500.50,INR,success,Food,ACC1,
        T2,05-09-2024,Netflix,$9.99,USD,success,Entertainment,ACC1,
        """
        df, _ = clean_data(_csv_to_file(csv, tmp_path))
        assert df['amount'].iloc[0] == pytest.approx(1500.50)
        assert df['amount'].iloc[1] == pytest.approx(9.99)

    def test_uppercase_status_and_currency(self, tmp_path):
        csv = """
        txn_id,date,merchant,amount,currency,status,category,account_id,notes
        T1,04-09-2024,Swiggy,250,inr,Success,Food,ACC1,
        """
        df, _ = clean_data(_csv_to_file(csv, tmp_path))
        assert df['status'].iloc[0] == 'SUCCESS'
        assert df['currency'].iloc[0] == 'INR'

    def test_fills_missing_category(self, tmp_path):
        csv = """
        txn_id,date,merchant,amount,currency,status,category,account_id,notes
        T1,04-09-2024,SomeMerchant,250,INR,success,,ACC1,
        """
        df, _ = clean_data(_csv_to_file(csv, tmp_path))
        assert df['category'].iloc[0] == 'Uncategorised'

    def test_dedup_after_normalization_catches_format_dupes(self, tmp_path):
        """Two rows identical logically but with different date/amount formats should be deduped."""
        csv = """
        txn_id,date,merchant,amount,currency,status,category,account_id,notes
        T1,04-09-2024,Swiggy,₹250,INR,success,Food,ACC1,lunch
        T2,2024/09/04,Swiggy,250,INR,SUCCESS,Food,ACC1,lunch
        """
        df, raw_count = clean_data(_csv_to_file(csv, tmp_path))
        assert raw_count == 2
        assert len(df) == 1   # logical duplicate removed after normalization

    def test_missing_column_added_as_none(self, tmp_path):
        csv = """
        txn_id,date,merchant,amount,currency,status
        T1,04-09-2024,Swiggy,250,INR,success
        """
        df, _ = clean_data(_csv_to_file(csv, tmp_path))
        assert 'category' in df.columns
        assert 'account_id' in df.columns


# ── detect_anomalies ────────────────────────────────────────────────────────────

from utils import detect_anomalies


class TestDetectAnomalies:
    def _base_df(self):
        return pd.DataFrame({
            'account_id': ['ACC1', 'ACC1', 'ACC1', 'ACC1'],
            'merchant': ['Swiggy', 'Zomato', 'Netflix', 'Amazon'],
            'amount': [100.0, 120.0, 110.0, 115.0],
            'currency': ['INR', 'INR', 'INR', 'INR'],
            'is_anomaly': [False, False, False, False],
            'anomaly_reason': [None, None, None, None],
        })

    def test_amount_spike_flagged(self):
        df = self._base_df()
        df.loc[3, 'amount'] = 900.0   # > 3× median(~110) = 330
        df = detect_anomalies(df)
        assert df.loc[3, 'is_anomaly'] is True or df.loc[3, 'is_anomaly'] == True
        assert df.loc[0, 'is_anomaly'] is False or df.loc[0, 'is_anomaly'] == False

    def test_domestic_brand_usd_flagged(self):
        df = pd.DataFrame({
            'account_id': ['ACC1'],
            'merchant': ['Swiggy'],
            'amount': [9.99],
            'currency': ['USD'],
            'is_anomaly': [False],
            'anomaly_reason': [None],
        })
        df = detect_anomalies(df)
        assert df.loc[0, 'is_anomaly'] == True
        assert 'domestic' in df.loc[0, 'anomaly_reason'].lower()

    def test_motorola_not_flagged_as_ola(self):
        """Word-boundary fix: 'ola' inside 'Motorola' must NOT trigger the domestic brand rule."""
        df = pd.DataFrame({
            'account_id': ['ACC1'],
            'merchant': ['Motorola'],
            'amount': [50.0],
            'currency': ['USD'],
            'is_anomaly': [False],
            'anomaly_reason': [None],
        })
        df = detect_anomalies(df)
        assert df.loc[0, 'is_anomaly'] == False

    def test_inr_domestic_brand_not_flagged(self):
        """Domestic brand + INR currency should NOT be an anomaly."""
        df = pd.DataFrame({
            'account_id': ['ACC1'],
            'merchant': ['Swiggy'],
            'amount': [250.0],
            'currency': ['INR'],
            'is_anomaly': [False],
            'anomaly_reason': [None],
        })
        df = detect_anomalies(df)
        assert df.loc[0, 'is_anomaly'] == False

    def test_empty_dataframe_does_not_crash(self):
        df = pd.DataFrame(columns=['account_id', 'merchant', 'amount', 'currency'])
        df = detect_anomalies(df)
        assert df.empty


# ── _compute_aggregates ────────────────────────────────────────────────────────

from tasks import _compute_aggregates


class TestComputeAggregates:
    def _sample_df(self):
        return pd.DataFrame({
            'merchant': ['Swiggy', 'Zomato', 'Netflix', 'Amazon', 'Swiggy'],
            'amount': [200.0, 300.0, 500.0, 1000.0, 150.0],
            'currency': ['INR', 'INR', 'USD', 'USD', 'INR'],
            'category': ['Food', 'Food', 'Entertainment', 'Shopping', 'Food'],
            'is_anomaly': [False, False, False, True, False],
        })

    def test_total_spend_inr(self):
        agg = _compute_aggregates(self._sample_df())
        # 200 + 300 + 150 = 650
        assert agg['total_spend_inr'] == pytest.approx(650.0)

    def test_total_spend_usd(self):
        agg = _compute_aggregates(self._sample_df())
        # 500 + 1000 = 1500
        assert agg['total_spend_usd'] == pytest.approx(1500.0)

    def test_anomaly_count_is_exact(self):
        agg = _compute_aggregates(self._sample_df())
        assert agg['anomaly_count'] == 1

    def test_top_merchants_correct_and_limited_to_3(self):
        agg = _compute_aggregates(self._sample_df())
        top = agg['top_merchants']
        assert len(top) <= 3
        # Amazon (1000) should be #1
        assert list(top.keys())[0] == 'Amazon'

    def test_per_category_spend_split_by_currency(self):
        agg = _compute_aggregates(self._sample_df())
        pcs = agg['per_category_spend']
        # Food: 200+300+150 INR, 0 USD
        assert pcs['Food']['INR'] == pytest.approx(650.0)
        assert 'USD' not in pcs['Food']
        # Entertainment: 500 USD only
        assert pcs['Entertainment']['USD'] == pytest.approx(500.0)
        assert 'INR' not in pcs['Entertainment']

    def test_currencies_never_mixed_into_single_number(self):
        """The old bug: INR+USD summed into one float. Verify it's now split."""
        agg = _compute_aggregates(self._sample_df())
        pcs = agg['per_category_spend']
        for cat, currencies in pcs.items():
            assert isinstance(currencies, dict), f"Category {cat} is not a currency dict"
