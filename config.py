import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BASE_URL = os.environ["OPENAI_BASE_URL"]
API_KEY = os.environ["OPENAI_API_KEY"]
MODEL = os.environ.get("MODEL", "deepseek-v4.1-flash-1017")

keys = {
    "railradar": os.environ.get("RAILRADAR_API_KEY"),
    "duffel": os.environ.get("DUFFEL_API_KEY"),
    "nuitee": os.environ.get("NUITEE_API_KEY"),
}
