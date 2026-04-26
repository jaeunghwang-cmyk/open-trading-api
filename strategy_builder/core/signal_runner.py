"""
시그널 러너

- 선택한 전략/종목을 서버에서 주기적으로 실행
- 실행 상태를 파일에 저장하여 재시작/재접속 후 복원
- 자동매매가 켜진 경우 서버에서 직접 주문 실행
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from backend import get_current_mode, is_authenticated
from core.data_fetcher import get_current_price, get_holdings


logger = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".kis_strategy_builder"
STATE_FILE = STATE_DIR / "signal_runner.json"
DEFAULT_INTERVAL_SECONDS = 20

_state_lock = threading.Lock()
_run_lock = threading.Lock()


def _default_state() -> Dict[str, Any]:
    return {
        "active": False,
        "session": None,
        "last_started_at": None,
        "last_stopped_at": None,
        "last_run_at": None,
        "last_error": None,
        "last_results": [],
        "last_logs": [],
    }


def _load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return _default_state()
    try:
        loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {**_default_state(), **loaded}
    except Exception:
        return _default_state()


def _save_state(state: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def get_runner_status() -> Dict[str, Any]:
    with _state_lock:
        state = _load_state()
    state["authenticated"] = is_authenticated()
    state["current_mode"] = get_current_mode()
    return state


def start_runner(session: Dict[str, Any]) -> Dict[str, Any]:
    with _state_lock:
        state = _load_state()
        state["active"] = True
        state["session"] = {
            "strategy_id": session["strategy_id"],
            "stocks": session["stocks"],
            "params": session.get("params", {}),
            "builder_state": session.get("builder_state"),
            "auto_trade": bool(session.get("auto_trade", False)),
            "interval_seconds": int(session.get("interval_seconds") or DEFAULT_INTERVAL_SECONDS),
        }
        state["last_started_at"] = datetime.now().isoformat()
        state["last_stopped_at"] = None
        state["last_error"] = None
        state["last_run_at"] = None
        _save_state(state)
        return state


def stop_runner() -> Dict[str, Any]:
    with _state_lock:
        state = _load_state()
        state["active"] = False
        state["last_stopped_at"] = datetime.now().isoformat()
        state["last_error"] = None
        _save_state(state)
        return state


def _should_run(state: Dict[str, Any]) -> bool:
    if not state.get("active"):
        return False
    session = state.get("session") or {}
    interval = int(session.get("interval_seconds") or DEFAULT_INTERVAL_SECONDS)
    last_run_at = state.get("last_run_at")
    if not last_run_at:
        return True
    try:
        last_run = datetime.fromisoformat(last_run_at)
    except ValueError:
        return True
    return datetime.now() >= last_run + timedelta(seconds=interval)


def _serialize_response(response: Any) -> tuple[list[dict], list[dict], str | None]:
    results = []
    for item in getattr(response, "results", []) or []:
        if hasattr(item, "model_dump"):
            results.append(item.model_dump())
        else:
            results.append(dict(item))

    logs = []
    for item in getattr(response, "logs", []) or []:
        if hasattr(item, "model_dump"):
            logs.append(item.model_dump())
        else:
            logs.append(dict(item))

    return results, logs, getattr(response, "message", None)


def _build_order_request(signal: Dict[str, Any], env_dv: str):
    from backend.routers.orders import OrderRequest

    action = signal.get("action")
    if action not in ("BUY", "SELL"):
        return None

    stock_code = str(signal.get("code", ""))
    stock_name = str(signal.get("name", stock_code))
    target_price = signal.get("target_price")
    strategy_context = signal.get("strategy_context") or {}

    current_price = int(target_price or 0)
    price_data = get_current_price(stock_code, env_dv)
    if price_data.get("price"):
        current_price = int(price_data["price"])

    quantity = signal.get("quantity")
    if not quantity and action == "SELL":
        holdings = get_holdings(env_dv)
        matched = holdings[holdings["stock_code"] == stock_code] if not holdings.empty else holdings
        if not matched.empty:
            quantity = int(matched.iloc[0]["quantity"])
    if not quantity and action == "BUY":
        quantity = 1

    quantity = int(quantity or 0)
    if quantity <= 0:
        return None

    reserve_order = bool(strategy_context.get("reserve_order"))
    order_type = "limit" if target_price or reserve_order else "market"

    return OrderRequest(
        stock_code=stock_code,
        stock_name=stock_name,
        action=action,
        order_type=order_type,
        price=int(target_price or current_price or 0),
        quantity=quantity,
        signal_reason=str(signal.get("reason") or "자동 시그널 주문"),
        strategy_context=strategy_context,
    )


async def _execute_auto_orders(results: List[Dict[str, Any]], env_dv: str) -> None:
    from backend.routers.orders import execute_order_internal

    for signal in results:
        request = _build_order_request(signal, env_dv)
        if request is None:
            continue
        try:
            await execute_order_internal(request)
        except Exception as exc:
            logger.warning("자동 주문 실행 실패 (%s): %s", signal.get("code"), exc)


async def run_runner_cycle() -> None:
    if not is_authenticated():
        return

    with _state_lock:
        state = _load_state()

    if not _should_run(state):
        return

    if not _run_lock.acquire(blocking=False):
        return

    try:
        with _state_lock:
            state = _load_state()
        if not _should_run(state):
            return

        session = state.get("session") or {}
        env_dv = get_current_mode()

        from backend.routers.strategy import ExecuteRequest, execute_strategy_once

        request = ExecuteRequest(
            strategy_id=session["strategy_id"],
            stocks=list(session.get("stocks") or []),
            params=dict(session.get("params") or {}),
            builder_state=session.get("builder_state"),
            auto_trade=bool(session.get("auto_trade", False)),
        )
        response = execute_strategy_once(request)
        results, logs, message = _serialize_response(response)

        with _state_lock:
            latest = _load_state()
            latest["last_run_at"] = datetime.now().isoformat()
            latest["last_results"] = results
            latest["last_logs"] = logs
            latest["last_error"] = None if response.status == "success" else (message or "실행 실패")
            _save_state(latest)

        if response.status == "success" and session.get("auto_trade"):
            await _execute_auto_orders(results, env_dv)

    except Exception as exc:
        logger.exception("시그널 러너 실행 실패: %s", exc)
        with _state_lock:
            latest = _load_state()
            latest["last_run_at"] = datetime.now().isoformat()
            latest["last_error"] = str(exc)
            _save_state(latest)
    finally:
        _run_lock.release()
