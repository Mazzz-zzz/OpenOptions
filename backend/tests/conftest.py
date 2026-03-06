"""Shared test fixtures."""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Use SQLite for tests
os.environ["ENVIRONMENT"] = "development"
os.environ["DB_HOST"] = ""
os.environ["ALLOWED_IPS_CSV"] = ""
os.environ["TASTYTRADE_REFRESH_TOKEN"] = ""
os.environ["TASTYTRADE_CLIENT_ID"] = ""
os.environ["TASTYTRADE_CLIENT_SECRET"] = ""

from app.database import get_db
from app.main import app
from app.models import Alert, Base, Contract, Snapshot, Underlying


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db(engine) -> Generator[Session, None, None]:
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db) -> TestClient:
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_contract(db) -> Contract:
    contract = Contract(
        symbol="BTC-27JUN26-100000-C",
        underlying="BTC",
        market="crypto",
        source="deribit",
        strike=100000,
        expiry=date(2026, 6, 27),
        option_type="C",
    )
    db.add(contract)
    db.flush()
    return contract


@pytest.fixture
def sample_snapshot(db, sample_contract) -> Snapshot:
    snapshot = Snapshot(
        contract_id=sample_contract.id,
        bid=5000.0,
        ask=5200.0,
        mid=5100.0,
        market_iv=0.65,
        model_iv=0.60,
        delta_market=0.45,
        delta_model=0.42,
        vega=150.0,
        deviation=0.05,
        net_edge=0.04,
        triggered_by="user",
    )
    db.add(snapshot)
    db.flush()
    return snapshot


@pytest.fixture
def sample_alert(db, sample_snapshot) -> Alert:
    alert = Alert(
        snapshot_id=sample_snapshot.id,
        signal_type="surface_outlier",
    )
    db.add(alert)
    db.flush()
    return alert


@pytest.fixture
def future_expiry() -> date:
    return date.today() + timedelta(days=90)
