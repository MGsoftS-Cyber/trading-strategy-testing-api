"""Daily USD spot candle contracts. Prices and volumes arrive as decimal strings."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import ConfigDict, Field, field_validator, model_validator
from .auth_schemas import Credentials, StrictModel  # noqa: F401

Number = Annotated[Decimal, Field(ge=0, le=Decimal("1e15"), max_digits=28, decimal_places=12, allow_inf_nan=False)]
Market = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]


def utc_today():
    return datetime.now(timezone.utc).date()


class WorkspaceInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    quote_currency: Literal["USD"] = "USD"


class CandleInput(StrictModel):
    date: date
    market_id: Market
    open: Number
    high: Number
    low: Number
    close: Number
    volume: Number

    @field_validator("open", "high", "low", "close", "volume", mode="before")
    @classmethod
    def strings(cls, v):
        if not isinstance(v, str):
            raise ValueError("Send OHLC prices and base-asset volume as decimal strings.")
        return v

    @model_validator(mode="after")
    def valid(self):
        if self.date >= utc_today():
            raise ValueError("Only completed UTC daily candles are accepted.")
        if self.low <= 0 or not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("Require 0 < low <= open/close <= high.")
        return self


class DatasetInput(StrictModel):
    source: str = Field(min_length=1, max_length=200)
    venue: str = Field(min_length=1, max_length=80)
    quote_currency: Literal["USD"] = "USD"
    coverage_end: date
    candles: list[CandleInput] = Field(min_length=1, max_length=15000)

    @field_validator("coverage_end")
    @classmethod
    def completed(cls, v):
        if v >= utc_today():
            raise ValueError("Coverage end must be a completed UTC day.")
        return v


class CsvInput(StrictModel):
    candles_csv: str = Field(min_length=1, max_length=4000000)
    source: str = Field(min_length=1, max_length=200)
    venue: str = Field(min_length=1, max_length=80)
    coverage_end: date
    quote_currency: Literal["USD"] = "USD"


class BacktestInput(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_default=True)
    dataset_id: str = Field(min_length=1, max_length=36)
    market_id: Market
    start_date: date
    end_date: date
    name: str = Field(default="Strategy experiment", min_length=1, max_length=120)
    strategy: Literal["sma_cross", "rsi_reversion"] = "sma_cross"
    initial_cash: Annotated[
        Decimal, Field(gt=0, le=Decimal("1e12"), max_digits=28, decimal_places=12, allow_inf_nan=False)
    ] = "10000"
    fee_rate: Annotated[
        Decimal, Field(ge=0, le=Decimal("0.05"), max_digits=12, decimal_places=8, allow_inf_nan=False)
    ] = "0.001"
    slippage_rate: Annotated[
        Decimal, Field(ge=0, le=Decimal("0.05"), max_digits=12, decimal_places=8, allow_inf_nan=False)
    ] = "0.001"
    fast_period: int = Field(default=10, ge=2, le=99, strict=True)
    slow_period: int = Field(default=30, ge=3, le=100, strict=True)
    rsi_period: int = Field(default=14, ge=2, le=50, strict=True)
    rsi_low: float = Field(default=30, gt=0, lt=100, allow_inf_nan=False)
    rsi_high: float = Field(default=70, gt=0, lt=100, allow_inf_nan=False)
    enable_ml: bool = True

    @field_validator("initial_cash", "fee_rate", "slippage_rate", mode="before")
    @classmethod
    def decimal_strings(cls, v):
        if not isinstance(v, str):
            raise ValueError("Send initial_cash, fee_rate and slippage_rate as decimal strings.")
        return v

    @model_validator(mode="after")
    def valid(self):
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be earlier than end_date.")
        if self.fast_period >= self.slow_period:
            raise ValueError("fast_period must be below slow_period.")
        if self.rsi_low >= self.rsi_high:
            raise ValueError("rsi_low must be below rsi_high.")
        return self


class ComparisonInput(StrictModel):
    backtest_ids: list[Annotated[str, Field(min_length=1, max_length=36)]] = Field(min_length=2, max_length=10)

    @field_validator("backtest_ids")
    @classmethod
    def unique(cls, v):
        if len(set(v)) != len(v):
            raise ValueError("Use distinct saved backtest IDs.")
        return v
