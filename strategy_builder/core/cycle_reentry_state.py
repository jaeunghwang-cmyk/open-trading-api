"""
반복 분할매수 사이클 상태 저장

- 종목별 마지막 매수가
- 현재 몇 차까지 진입했는지
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


STATE_DIR = Path.home() / ".kis_strategy_builder"
STATE_FILE = STATE_DIR / "cycle_reentry_state.json"


def _load_all() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_all_states() -> Dict[str, Any]:
    return _load_all()


def _save_all(state: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_state(strategy_key: str, stock_code: str) -> Dict[str, Any]:
    state = _load_all()
    return state.get(strategy_key, {}).get(stock_code, {})


def set_state(strategy_key: str, stock_code: str, value: Dict[str, Any]) -> None:
    state = _load_all()
    state.setdefault(strategy_key, {})[stock_code] = value
    _save_all(state)


def update_state(strategy_key: str, stock_code: str, value: Dict[str, Any]) -> None:
    state = _load_all()
    bucket = state.setdefault(strategy_key, {}).get(stock_code, {})
    bucket.update(value)
    state.setdefault(strategy_key, {})[stock_code] = bucket
    _save_all(state)


def clear_pending_order(strategy_key: str, stock_code: str) -> None:
    state = _load_all()
    strategy_bucket = state.get(strategy_key, {})
    entry = strategy_bucket.get(stock_code, {})
    if not entry:
        return
    for key in ("pending_order_id", "pending_order_type", "pending_submitted_at"):
        entry.pop(key, None)
    strategy_bucket[stock_code] = entry
    state[strategy_key] = strategy_bucket
    _save_all(state)


def clear_pending_orders_for_stocks(stock_codes: list[str] | None = None) -> int:
    state = _load_all()
    targets = set(stock_codes or [])
    cleared = 0

    for strategy_key, strategy_bucket in list(state.items()):
        for stock_code, entry in list(strategy_bucket.items()):
            if targets and stock_code not in targets:
                continue
            had_pending = any(
                key in entry for key in ("pending_order_id", "pending_order_type", "pending_submitted_at")
            )
            if not had_pending:
                continue
            for key in ("pending_order_id", "pending_order_type", "pending_submitted_at"):
                entry.pop(key, None)
            strategy_bucket[stock_code] = entry
            cleared += 1
        state[strategy_key] = strategy_bucket

    _save_all(state)
    return cleared


def clear_state(strategy_key: str, stock_code: str) -> None:
    state = _load_all()
    strategy_bucket = state.get(strategy_key, {})
    strategy_bucket.pop(stock_code, None)
    if not strategy_bucket:
        state.pop(strategy_key, None)
    _save_all(state)
