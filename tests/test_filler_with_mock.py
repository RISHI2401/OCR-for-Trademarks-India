import pandas as pd
from pathlib import Path
import tempfile
from pipelines.trademark_filler import TrademarkFiller


def test_filler_merges_mock_trademarks(tmp_path):
    # Create a small main CSV
    main = pd.DataFrame({
        'application_number': ['A1', 'A2', 'A3'],
        'trademark_text': ['', '', 'Existing']
    })
    main_csv = tmp_path / 'main.csv'
    main.to_csv(main_csv, index=False)

    # Create a trademark CSV (mocked)
    dict_df = pd.DataFrame({
        'application_number': ['A1', 'A2'],
        'trademark_text': ['TM_ONE', 'TM_TWO']
    })
    dict_csv = tmp_path / 'trademarks.csv'
    dict_df.to_csv(dict_csv, index=False)

    # Run filler
    out_csv = tmp_path / 'out.csv'
    filler = TrademarkFiller()
    result = filler.fill(main_csv, dict_csv, out_csv)

    df = pd.read_csv(result)
    # A1 and A2 should be filled, A3 should retain existing
    assert df.loc[df.application_number == 'A1', 'trademark_text'].iloc[0] == 'TM_ONE'
    assert df.loc[df.application_number == 'A2', 'trademark_text'].iloc[0] == 'TM_TWO'
    assert df.loc[df.application_number == 'A3', 'trademark_text'].iloc[0] == 'Existing'
