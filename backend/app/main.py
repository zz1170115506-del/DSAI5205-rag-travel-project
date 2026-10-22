from fastapi import FastAPI

from app.api.travel import router as travel_router


app = FastAPI(title="Travel RAG Backend")

app.include_router(travel_router)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}