from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.routes import router

app = FastAPI(title="AI Coding Platform", version="0.1.0")
app.include_router(router, prefix="/api")

app.mount("/assets", StaticFiles(directory="frontend"), name="assets")


@app.get("/")
def index() -> FileResponse:
    return FileResponse("frontend/index.html")
