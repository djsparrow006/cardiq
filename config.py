import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:pass@localhost/cardiq")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
TEXT_MODEL = "llama-3.3-70b-versatile"

CATEGORIES = ["education", "business", "vendor", "other"]

# Fuzzy-match threshold for dedup — two contacts with a similarity score
# at/above this on (name + company/email) are treated as the same person.
DEDUP_THRESHOLD = 0.82
