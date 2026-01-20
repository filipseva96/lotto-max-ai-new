"""
Configuration for Lotto AI
Fixed for Streamlit Cloud deployment
"""
from pathlib import Path
import os

# Get the project root directory
# Works both locally and on Streamlit Cloud
BASE_DIR = Path(__file__).resolve().parent.parent

# Data directory
DATA_DIR = BASE_DIR / "lotto_ai" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Database path
DB_PATH = DATA_DIR / "lotto_max.db"

# Models directory
MODELS_DIR = BASE_DIR / "lotto_ai" / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)