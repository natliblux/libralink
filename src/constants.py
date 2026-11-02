from pathlib import Path

PROJECT_PATH = Path(__file__).resolve().parent.parent
DB_FILE = PROJECT_PATH / "authorities.db"
TABLE_NAME = "authorities"
INDEXING_BATCH_SIZE = 1000
ALLOWED_SEARCH_FIELDS = ["variant", "variantA", "variantB"]
API_NAME = "LibraLink API"
API_PORT = 8766