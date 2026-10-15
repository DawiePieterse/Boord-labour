"""Dev entrypoint on LABOUR_PORT (8040), clear of Boord 8000/8811 and Owner 8010.

Set BOORD_DB_PATH if Boord isn't checked out at ../Boord:
    BOORD_DB_PATH=/path/to/boord/data/boord.db .venv/bin/python run_preview.py
"""
import os

import uvicorn

import config

uvicorn.run("main:app", host="127.0.0.1", port=config.LABOUR_PORT,
            app_dir=os.path.dirname(os.path.abspath(__file__)))
