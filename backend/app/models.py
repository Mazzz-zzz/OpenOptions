from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Underlying(Base):
    __tablename__ = "underlyings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(15), unique=True, nullable=False)
    market = Column(String(15), nullable=False)  # 'crypto' or 'equity'
    source = Column(String(15), nullable=False)  # 'deribit' or 'tastytrade'
    is_active = Column(Boolean, default=True)
    last_fetched_at = Column(DateTime(timezone=True))
    last_spot = Column(Numeric(18, 4))
    last_snapshot_count = Column(Integer, default=0)
    last_alert_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Contract(Base):
    __tablename__ = "contracts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(60), unique=True, nullable=False)
    underlying = Column(String(15), nullable=False)
    market = Column(String(15), nullable=False)  # 'crypto' or 'equity'
    source = Column(String(15), nullable=False)  # 'deribit' or 'tradier'
    strike = Column(Numeric(18, 4), nullable=False)
    expiry = Column(Date, nullable=False)
    option_type = Column(String(1), nullable=False)  # 'C' or 'P'
    is_watchlisted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    snapshots = relationship("Snapshot", back_populates="contract", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_contracts_underlying_watchlisted", "underlying", "is_watchlisted"),
    )


class Snapshot(Base):
    __tablename__ = "snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False)
    ts = Column(DateTime(timezone=True), server_default=func.now())
    bid = Column(Numeric(18, 4))
    ask = Column(Numeric(18, 4))
    mid = Column(Numeric(18, 4))
    market_iv = Column(Numeric(18, 6))
    model_iv = Column(Numeric(18, 6))
    delta_market = Column(Numeric(18, 6))
    delta_model = Column(Numeric(18, 6))
    vega = Column(Numeric(18, 6))
    gamma = Column(Numeric(18, 6))
    theta = Column(Numeric(18, 6))
    deviation = Column(Numeric(18, 6))
    net_edge = Column(Numeric(18, 6))
    triggered_by = Column(String(20))  # 'user' or 'schedule'

    contract = relationship("Contract", back_populates="snapshots")
    alerts = relationship("Alert", back_populates="snapshot", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_snapshots_contract_ts", "contract_id", "ts"),
        Index("ix_snapshots_ts", "ts"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(Integer, ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False)
    signal_type = Column(String(30), nullable=False)  # 'surface_outlier', 'greek_divergence'
    confidence = Column(String(10))  # 'high', 'medium', 'low'
    dismissed = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    snapshot = relationship("Snapshot", back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_dismissed_created", "dismissed", "created_at"),
    )
