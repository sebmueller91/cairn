from fastapi import FastAPI

from app.routers import (
    accounts,
    auth,
    health,
    import_batches,
    instruments,
    positions,
    transactions,
)

app = FastAPI(
    title="Cairn API",
    description="Self-hosted net worth and portfolio tracker.",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(instruments.router)
app.include_router(transactions.router)
app.include_router(positions.router)
app.include_router(import_batches.router)
