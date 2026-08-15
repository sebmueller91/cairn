from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.routers import (
    accounts,
    admin,
    auth,
    health,
    house_index,
    import_batches,
    instruments,
    loans,
    positions,
    price_sources,
    prices,
    reconcile,
    timeseries,
    transactions,
    valuations,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if get_settings().enable_scheduler:
        from app.scheduler import create_scheduler

        scheduler = create_scheduler()
        scheduler.start()
    yield
    if scheduler is not None:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="Cairn API",
    description="Self-hosted net worth and portfolio tracker.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(instruments.router)
app.include_router(price_sources.router)
app.include_router(prices.router)
app.include_router(transactions.router)
app.include_router(positions.router)
app.include_router(import_batches.router)
app.include_router(admin.router)
app.include_router(timeseries.router)
app.include_router(reconcile.router)
app.include_router(valuations.router)
app.include_router(house_index.router)
app.include_router(loans.router)
