from fastapi import APIRouter
from .database import get_db_cursor

health_router = APIRouter(tags=["health"])

@health_router.get("/health")
async def health_check():
    try:
        # Test database connection
        cur = get_db_cursor()
        cur.execute("SELECT 1")
        cur.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)} 