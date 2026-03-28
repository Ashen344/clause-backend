from dotenv import load_dotenv
import os
from pymongo import MongoClient

# Load variables from .env file into the environment
load_dotenv()

# Read each value from environment variables
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "clause_db")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")
CLERK_ISSUER = os.getenv("CLERK_ISSUER", "")
SECRET_KEY = os.getenv("SECRET_KEY", "default-secret-key")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

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
