"""
真實資料 ETL（取代 etl/extract_gcis_batch.py 等模擬資料）
每個模組負責一個來源：fetch() 下載原始檔到 data/raw/，transform() 產出 data/processed/ 的長表。
資料集代號對應 docs/DATA_CATALOG.md、docs/DATA_REQUIREMENTS.md。
"""
