from dotenv import load_dotenv
import os
from pathlib import Path
from pymongo import MongoClient

# Load variables from .env file into the environment
# Use explicit path so it works regardless of working directory
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

# Read each value from environment variables
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "Clause")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")
CLERK_ISSUER = os.getenv("CLERK_ISSUER", "")
SECRET_KEY = os.getenv("SECRET_KEY", "default-secret-key")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Google Calendar / OAuth
GOOGLE_CLIENT_ID    = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/calendar/callback")
FRONTEND_URL         = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Gmail SMTP  (use a Gmail address + App Password from Google Account settings)
SMTP_EMAIL    = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# Create the MongoDB client connection
client = MongoClient(MONGODB_URI)

# Get a reference to your specific database
db = client[DATABASE_NAME]

# Define your collections (like tables in SQL)
users_collection = db["users"]
contracts_collection = db["contracts"]
audit_logs_collection = db["audit_logs"]
notifications_collection = db["notifications"]
templates_collection = db["templates"]
workflows_collection = db["workflows"]
approvals_collection = db["approvals"]
calendar_tokens_collection = db["calendar_tokens"]
