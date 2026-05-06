import importlib, sys
sys.path.insert(0, '.')
try:
    te = importlib.import_module('trademark_extractor')
    print('trademark_extractor imported, has extract_trademarks =', hasattr(te, 'extract_trademarks'))
    # call extract_trademarks on one chunk
    p = 'output/outputs/pdf3_chunk1-half/pdf_chunks/pdf3_chunk1-half_chunk_1_pages_1-20.pdf'
    print('calling extract_trademarks on', p)
    data = te.extract_trademarks(p)
    print('extract_trademarks returned:', type(data), 'len:', len(data) if hasattr(data, '__len__') else 'n/a')
except Exception as e:
    print('ERROR:', e)
