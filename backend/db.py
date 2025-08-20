# backend/db.py
from __future__ import annotations

import os
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Optional: load .env (DATABASE_URL, CORS_ORIGINS)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Accept common env var names for Postgres URLs
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("PG_URL")
    or os.getenv("POSTGRES_URL")
    or os.getenv("POSTGRES_URI")
    or os.getenv("DB_URL")
)

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL (or PG_URL/POSTGRES_URL/POSTGRES_URI/DB_URL) is not set."
        " Put it in backend/.env or export it in your shell."
    )

# Create the engine instance that other files can import
engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

# Declarative base (needed by models.py)
Base = declarative_base()

# Optional if you ever need ORM sessions
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)

# Keep the function for compatibility if other parts of the app use it
def get_engine() -> Engine:
    return engine
