from pathlib import Path
import sys
sys.path.insert(0, '.')
from pipelines.trademark_extractor import TrademarkExtractor
import pandas as pd

chunks_dir = Path('output/outputs/pdf3_chunk1-half/pdf_chunks')
out_csv = Path('output/outputs/pdf3_chunk1-half/csv/test_trademarks_mock.csv')

ext = TrademarkExtractor(mock=True)
res = ext.extract(chunks_dir, out_csv)
print('Wrote:', res)
if res.exists():
    df = pd.read_csv(res)
    print('Rows:', len(df))
    print(df.head())
else:
    print('No output file created')
