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
    last_fetched_at = Column(DateTime(timezone=True))
    last_spot = Column(Numeric(18, 4))
    last_snapshot_count = Column(Integer, default=0)
    last_alert_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Market metrics from Tastytrade
    iv_index = Column(Numeric(18, 6))
    iv_index_5d_change = Column(Numeric(18, 6))
    iv_rank = Column(Numeric(8, 2))
    iv_percentile = Column(Numeric(8, 2))
    liquidity = Column(Numeric(18, 4))
    liquidity_rank = Column(Numeric(18, 4))
    liquidity_rating = Column(Integer)

    earnings = relationship("Earning", back_populates="underlying_rel", cascade="all, delete-orphan")
    dividends = relationship("Dividend", back_populates="underlying_rel", cascade="all, delete-orphan")


class Earning(Base):
    __tablename__ = "earnings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    underlying_id = Column(Integer, ForeignKey("underlyings.id", ondelete="CASCADE"), nullable=False)
    occurred_date = Column(Date, nullable=False)
    eps = Column(Numeric(12, 4))

    underlying_rel = relationship("Underlying", back_populates="earnings")

    __table_args__ = (
        Index("ix_earnings_underlying_date", "underlying_id", "occurred_date", unique=True),
    )


class Dividend(Base):
    __tablename__ = "dividends"

    id = Column(Integer, primary_key=True, autoincrement=True)
    underlying_id = Column(Integer, ForeignKey("underlyings.id", ondelete="CASCADE"), nullable=False)
    occurred_date = Column(Date, nullable=False)
    amount = Column(Numeric(12, 6))

    underlying_rel = relationship("Underlying", back_populates="dividends")

    __table_args__ = (
        Index("ix_dividends_underlying_date", "underlying_id", "occurred_date", unique=True),
    )


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
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    snapshots = relationship("Snapshot", back_populates="contract", cascade="all, delete-orphan")


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


# ── ML / Numerai models ──────────────────────────────────────────────


class MlExperiment(Base):
    __tablename__ = "ml_experiments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), unique=True, nullable=False)
    description = Column(String(500))
    status = Column(String(20), nullable=False, default="active")  # active, archived
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    runs = relationship("MlRun", back_populates="experiment", cascade="all, delete-orphan")


class MlRun(Base):
    __tablename__ = "ml_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id = Column(Integer, ForeignKey("ml_experiments.id", ondelete="CASCADE"), nullable=False)
    model_type = Column(String(30), nullable=False)  # lgbm, tabnet, ensemble
    status = Column(String(20), nullable=False, default="pending")  # pending, running, completed, failed
    hyperparams_json = Column(String(4000))
    correlation = Column(Numeric(10, 6))
    sharpe = Column(Numeric(10, 6))
    feature_exposure = Column(Numeric(10, 6))
    max_drawdown = Column(Numeric(10, 6))
    progress_pct = Column(Numeric(5, 2), default=0)
    current_epoch = Column(Integer, default=0)
    total_epochs = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    experiment = relationship("MlExperiment", back_populates="runs")
    epoch_metrics = relationship("MlEpochMetric", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_ml_runs_experiment_status", "experiment_id", "status"),
    )


class MlEpochMetric(Base):
    __tablename__ = "ml_epoch_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("ml_runs.id", ondelete="CASCADE"), nullable=False)
    epoch = Column(Integer, nullable=False)
    train_loss = Column(Numeric(10, 6))
    val_loss = Column(Numeric(10, 6))
    correlation = Column(Numeric(10, 6))
    sharpe = Column(Numeric(10, 6))

    run = relationship("MlRun", back_populates="epoch_metrics")

    __table_args__ = (
        Index("ix_ml_epoch_metrics_run_epoch", "run_id", "epoch", unique=True),
    )


class MlModel(Base):
    __tablename__ = "ml_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), unique=True, nullable=False)
    model_type = Column(String(30), nullable=False)
    stage = Column(String(20), nullable=False, default="dev")  # dev, staging, prod
    version = Column(Integer, nullable=False, default=1)
    run_id = Column(Integer, ForeignKey("ml_runs.id", ondelete="SET NULL"))
    correlation = Column(Numeric(10, 6))
    sharpe = Column(Numeric(10, 6))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    run = relationship("MlRun")

    __table_args__ = (
        Index("ix_ml_models_stage", "stage"),
    )


class MlRound(Base):
    __tablename__ = "ml_rounds"

    id = Column(Integer, primary_key=True, autoincrement=True)
    round_number = Column(Integer, nullable=False)
    model_name = Column(String(120), nullable=False)
    live_corr = Column(Numeric(10, 6))
    resolved_corr = Column(Numeric(10, 6))
    payout_nmr = Column(Numeric(10, 6))
    status = Column(String(20), nullable=False, default="pending")  # pending, resolved
    submitted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ml_rounds_round_model", "round_number", "model_name", unique=True),
    )


class MlEnsemble(Base):
    __tablename__ = "ml_ensembles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    method = Column(String(30), nullable=False)  # rank_average, weighted_blend
    config_json = Column(String(4000))
    correlation = Column(Numeric(10, 6))
    sharpe = Column(Numeric(10, 6))
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ml_ensembles_active", "is_active"),
    )
