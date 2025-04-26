import logging
from fastapi import FastAPI
from api.routes import webhook_router


logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Initialize FastAPI app
app = FastAPI(title="WhatsApp Bot API")


app.include_router(webhook_router)    

@app.get("/")
def read_root():
    return {"message": "Welcome to the WhatsApp Bot Server"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True) 