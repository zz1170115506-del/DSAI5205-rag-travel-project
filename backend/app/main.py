from fastapi import FastAPI

app = FastAPI(title="Travel RAG Backend")


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}