import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv
import logging
import time
# env_path = r"D:\Sena Projects\test_aladdin_bot_cursor\.env"
load_dotenv()
# Configure logging to show in terminal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # This will output to terminal
        logging.FileHandler('database.log')  # This will save to a file
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def get_db_credentials():
    """Get and validate database credentials"""
    credentials = {
        'host': os.getenv('DB_HOST'),
        'port': os.getenv('DB_PORT'),
        'database': os.getenv('DB_NAME'),
        'user': os.getenv('DB_USER'),
        'password': os.getenv('DB_PASSWORD')
    }
    
    # Validate all credentials are present
    missing = [k for k, v in credentials.items() if not v]
    if missing:
        raise ValueError(f"Missing database credentials: {', '.join(missing)}")
    
    logger.info(f"Using database credentials: host={credentials['host']}, port={credentials['port']}, db={credentials['database']}, user={credentials['user']}")
    return credentials

def get_db_connection():
    """Establish a new database connection"""
    max_retries = 5
    retry_delay = 2  # seconds
    
    credentials = get_db_credentials()
    
    for attempt in range(max_retries):
        try:
            # Create database connection
            conn = psycopg2.connect(
                **credentials,
                cursor_factory=RealDictCursor
            )
            
            # Test the connection
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                logger.info("Successfully connected to the database")
                return conn
                
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Connection attempt {attempt + 1} failed: {str(e)}")
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error(f"Failed to connect to database after {max_retries} attempts: {str(e)}")
                logger.error("Please check:")
                logger.error("1. PostgreSQL service is running")
                logger.error("2. Database credentials in .env file are correct")
                logger.error("3. Database 'Aladdin_Leads_Db' exists")
                logger.error("4. User has correct permissions")
                logger.error(f"Current connection details: {credentials}")
                raise

def get_db_cursor():
    """Get a new database cursor with a new connection"""
    conn = get_db_connection()
    return conn, conn.cursor()

def commit_changes(conn):
    """Commit changes and close the connection"""
    try:
        conn.commit()
        logger.info("Transaction committed successfully")
    except Exception as e:
        logger.error(f"Error committing transaction: {str(e)}")
        raise
    finally:
        conn.close()
        logger.info("Database connection closed")

def execute_query(query, params=None):
    """Execute a query and return results"""
    conn, cur = get_db_cursor()
    try:
        cur.execute(query, params)
        if cur.description:  # If query returns results
            results = cur.fetchall()
            return results
        return None
    except Exception as e:
        logger.error(f"Error executing query: {str(e)}")
        raise
    finally:
        commit_changes(conn) 