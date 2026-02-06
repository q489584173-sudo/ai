"""Simple quantitative trading strategy backtest.

Usage:
    python quant_strategy.py 路径/到/行情.csv --strategy sma --short 20 --long 50
    python quant_strategy.py 路径/到/行情.csv --strategy rsi --rsi-window 14 --rsi-low 30 --rsi-high 70
    python quant_strategy.py 路径/到/行情.csv --strategy buyhold

CSV format:
    date,close
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from statistics import mean
from typing import Iterable, List, Optional, Sequence


@dataclass
class Bar:
    date: str
    close: float


@dataclass
class TradeResult:
    total_return: float
    annualized_return: float
    max_drawdown: float
    win_rate: float
    num_trades: int
    sharpe_ratio: float
    volatility: float


def read_prices(path: str) -> List[Bar]:
    with open(path, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        bars: List[Bar] = []
        for row in reader:
            if "date" not in row or "close" not in row:
                raise ValueError("CSV 必须包含 'date' 和 'close' 列")
            bars.append(Bar(date=row["date"], close=float(row["close"])))
    return bars


def rolling_mean(values: List[float], window: int) -> List[float]:
    if window <= 0:
        raise ValueError("窗口长度必须为正数")
    averages = []
    for idx in range(len(values)):
        if idx + 1 < window:
            averages.append(float("nan"))
        else:
            averages.append(mean(values[idx + 1 - window : idx + 1]))
    return averages


def rolling_rsi(values: List[float], window: int) -> List[float]:
    if window <= 0:
        raise ValueError("窗口长度必须为正数")
    rsis: List[float] = []
    gains: List[float] = []
    losses: List[float] = []
    for idx in range(1, len(values)):
        delta = values[idx] - values[idx - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
        if idx < window:
            rsis.append(float("nan"))
            continue
        avg_gain = mean(gains[-window:])
        avg_loss = mean(losses[-window:])
        if avg_loss == 0:
            rsis.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsis.append(100 - (100 / (1 + rs)))
    rsis.insert(0, float("nan"))
    return rsis


def generate_signals(prices: List[float], short_window: int, long_window: int) -> List[int]:
    if short_window >= long_window:
        raise ValueError("短期窗口必须小于长期窗口")
    short_ma = rolling_mean(prices, short_window)
    long_ma = rolling_mean(prices, long_window)
    signals: List[int] = []
    for short, long in zip(short_ma, long_ma):
        if short != short or long != long:
            signals.append(0)
        elif short > long:
            signals.append(1)
        else:
            signals.append(0)
    return signals


def generate_rsi_signals(prices: List[float], rsi_window: int, low: float, high: float) -> List[int]:
    if low >= high:
        raise ValueError("RSI 低阈值必须小于高阈值")
    rsis = rolling_rsi(prices, rsi_window)
    signals: List[int] = []
    for rsi in rsis:
        if rsi != rsi:
            signals.append(0)
        elif rsi < low:
            signals.append(1)
        elif rsi > high:
            signals.append(0)
        else:
            signals.append(signals[-1] if signals else 0)
    return signals


def generate_buyhold_signals(prices: List[float]) -> List[int]:
    if not prices:
        return []
    return [1] * len(prices)


def backtest(
    prices: List[float],
    signals: List[int],
    initial_capital: float = 1.0,
    fee_rate: float = 0.0,
) -> TradeResult:
    cash = initial_capital
    position = 0.0
    entry_price: Optional[float] = None
    equity_curve: List[float] = []
    trade_returns: List[float] = []
    daily_returns: List[float] = []

    for idx in range(1, len(prices)):
        if signals[idx - 1] == 1 and position == 0:
            position = (cash * (1 - fee_rate)) / prices[idx]
            entry_price = prices[idx]
            cash = 0.0
        elif signals[idx - 1] == 0 and position > 0:
            cash = position * prices[idx] * (1 - fee_rate)
            if entry_price is not None:
                trade_returns.append((prices[idx] - entry_price) / entry_price)
            position = 0.0
            entry_price = None

        equity = cash + position * prices[idx]
        if equity_curve:
            daily_returns.append((equity - equity_curve[-1]) / equity_curve[-1])
        equity_curve.append(equity)

    if position > 0:
        cash = position * prices[-1] * (1 - fee_rate)
        if entry_price is not None:
            trade_returns.append((prices[-1] - entry_price) / entry_price)
        equity_curve.append(cash)

    total_return = cash - 1.0
    num_years = max(len(prices) / 252.0, 1e-9)
    annualized_return = (cash ** (1 / num_years)) - 1
    max_drawdown = calculate_max_drawdown(equity_curve)
    win_rate = calculate_win_rate(trade_returns)
    volatility = calculate_volatility(daily_returns)
    sharpe_ratio = calculate_sharpe_ratio(daily_returns, volatility)

    return TradeResult(
        total_return=total_return,
        annualized_return=annualized_return,
        max_drawdown=max_drawdown,
        win_rate=win_rate,
        num_trades=len(trade_returns),
        sharpe_ratio=sharpe_ratio,
        volatility=volatility,
    )


def build_equity_curve(
    prices: List[float],
    signals: List[int],
    initial_capital: float,
    fee_rate: float,
) -> List[float]:
    cash = initial_capital
    position = 0.0
    equity_curve: List[float] = []
    for idx in range(1, len(prices)):
        if signals[idx - 1] == 1 and position == 0:
            position = (cash * (1 - fee_rate)) / prices[idx]
            cash = 0.0
        elif signals[idx - 1] == 0 and position > 0:
            cash = position * prices[idx] * (1 - fee_rate)
            position = 0.0
        equity_curve.append(cash + position * prices[idx])
    return equity_curve


def calculate_max_drawdown(equity_curve: Iterable[float]) -> float:
    peak = 0.0
    max_drawdown = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown


def calculate_win_rate(trade_returns: Iterable[float]) -> float:
    returns = list(trade_returns)
    if not returns:
        return 0.0
    wins = sum(1 for value in returns if value > 0)
    return wins / len(returns)


def calculate_volatility(daily_returns: Iterable[float]) -> float:
    returns = list(daily_returns)
    if len(returns) < 2:
        return 0.0
    avg = mean(returns)
    variance = sum((value - avg) ** 2 for value in returns) / (len(returns) - 1)
    return (variance**0.5) * (252**0.5)


def calculate_sharpe_ratio(daily_returns: Iterable[float], volatility: float) -> float:
    returns = list(daily_returns)
    if not returns or volatility == 0:
        return 0.0
    avg_daily = mean(returns)
    return (avg_daily * 252) / volatility


def summarize(result: TradeResult) -> str:
    return (
        f"Total Return: {result.total_return:.2%}\n"
        f"Annualized Return: {result.annualized_return:.2%}\n"
        f"Max Drawdown: {result.max_drawdown:.2%}\n"
        f"Win Rate: {result.win_rate:.2%}\n"
        f"Trades: {result.num_trades}\n"
        f"Volatility: {result.volatility:.2%}\n"
        f"Sharpe Ratio: {result.sharpe_ratio:.2f}\n"
    )

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="量化策略回测（支持 SMA / RSI / 买入持有）。")
    parser.add_argument("csv", help="CSV 文件路径（包含 date,close 列）")
    parser.add_argument(
        "--strategy",
        choices=["sma", "rsi", "buyhold"],
        default="sma",
        help="策略类型：sma（均线交叉），rsi（超买超卖），buyhold（买入持有）",
    )
    parser.add_argument("--short", type=int, default=20, help="短期均线窗口")
    parser.add_argument("--long", type=int, default=50, help="长期均线窗口")
    parser.add_argument("--rsi-window", type=int, default=14, help="RSI 计算窗口")
    parser.add_argument("--rsi-low", type=float, default=30.0, help="RSI 低阈值（做多触发）")
    parser.add_argument("--rsi-high", type=float, default=70.0, help="RSI 高阈值（平仓触发）")
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=1.0,
        help="初始资金（用于计算总收益）",
    )
    parser.add_argument(
        "--fee-rate",
        type=float,
        default=0.0,
        help="单次交易手续费率（例如 0.001 = 0.1%%）",
    )
    parser.add_argument(
        "--export-equity",
        help="导出净值曲线到 CSV（可选）",
        default=None,
    )
    return parser


def export_equity_curve(path: str, dates: List[str], equity_curve: List[float]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "equity"])
        for date, equity in zip(dates, equity_curve):
            writer.writerow([date, f"{equity:.6f}"])


def main(argv: Sequence[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv[1:])

    bars = read_prices(args.csv)
    prices = [bar.close for bar in bars]
    dates = [bar.date for bar in bars]

    if args.strategy == "sma":
        if len(prices) < max(args.short, args.long):
            print("数据量不足，无法满足指定窗口长度。")
            return 1
        signals = generate_signals(prices, short_window=args.short, long_window=args.long)
    elif args.strategy == "rsi":
        if len(prices) < args.rsi_window:
            print("数据量不足，无法满足 RSI 窗口长度。")
            return 1
        signals = generate_rsi_signals(
            prices, rsi_window=args.rsi_window, low=args.rsi_low, high=args.rsi_high
        )
    else:
        signals = generate_buyhold_signals(prices)

    result = backtest(
        prices,
        signals,
        initial_capital=args.initial_capital,
        fee_rate=args.fee_rate,
    )
    print(summarize(result))
    if args.export_equity:
        equity_curve = build_equity_curve(prices, signals, args.initial_capital, args.fee_rate)
        export_equity_curve(args.export_equity, dates[1 : len(equity_curve) + 1], equity_curve)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
