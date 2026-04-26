"""
주문/체결 이력 추적기

- 주문 접수 이력 저장
- 계좌/미체결 비교로 체결 감지
- 반복 분할매수 상태 요약 제공
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from core.cycle_reentry_state import _load_all as load_cycle_states, clear_state
import pandas as pd

from core.data_fetcher import get_deposit, get_holdings, get_pending_orders, get_reserved_orders
from core.telegram_notifier import send_message


logger = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".kis_strategy_builder"
STATE_FILE = STATE_DIR / "execution_tracker.json"
MAX_HISTORY = 200
SYNC_INTERVAL_SECONDS = 8


def _default_state() -> Dict[str, Any]:
    return {
        "submitted_orders": {},
        "pending_orders": {},
        "holdings": {},
        "balance": {},
        "history": [],
        "last_synced_at": None,
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


def _append_history(state: Dict[str, Any], event: Dict[str, Any]) -> None:
    history = state.setdefault("history", [])
    event_id = event.get("event_id")
    if event_id and any(item.get("event_id") == event_id for item in history):
        return
    history.append(event)
    if len(history) > MAX_HISTORY:
        del history[:-MAX_HISTORY]


def _format_price(value: int | None) -> str:
    return f"{int(value or 0):,}원"


def _format_balance(balance_after: Dict[str, Any] | None) -> str:
    if not balance_after:
        return "-"
    return _format_price(int(balance_after.get("deposit", 0) or 0))


def _history_from_submission(order_no: str, order_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "event_id": f"submitted:{order_no}",
        "event_type": "order_submitted",
        "timestamp": order_data["timestamp"],
        "order_no": order_no,
        "stock_code": order_data["stock_code"],
        "stock_name": order_data["stock_name"],
        "action": order_data["action"],
        "order_type": order_data["order_type"],
        "quantity": order_data["quantity"],
        "price": order_data["price"],
        "step_index": order_data.get("step_index"),
        "strategy_key": order_data.get("strategy_key"),
        "avg_price_after": None,
        "balance_after": None,
        "note": order_data.get("signal_reason", ""),
    }


def _send_submission_notification(order_data: Dict[str, Any]) -> None:
    step_text = f"{order_data['step_index']}차 " if order_data.get("step_index") else ""
    order_label = "예약" if order_data.get("order_type") == "reserve" else ""
    action_label = "매수" if order_data["action"] == "BUY" else "매도"
    message = "\n".join([
        f"[주문 접수] {step_text}{order_label}{action_label}",
        f"종목: {order_data['stock_name']} ({order_data['stock_code']})",
        f"수량: {order_data['quantity']}주",
        f"주문가: {_format_price(order_data.get('price'))}",
        f"주문번호: {order_data['order_no']}",
        f"시각: {order_data['timestamp']}",
    ])
    send_message(message)


def record_order_submission(
    *,
    order_no: str,
    stock_code: str,
    stock_name: str,
    action: str,
    order_type: str,
    quantity: int,
    price: int,
    signal_reason: str,
    strategy_context: Dict[str, Any] | None,
) -> Dict[str, Any]:
    state = _load_state()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    strategy_context = strategy_context or {}
    order_data = {
        "order_no": order_no,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "action": action,
        "order_type": order_type,
        "quantity": quantity,
        "price": price,
        "signal_reason": signal_reason,
        "timestamp": timestamp,
        "strategy_key": strategy_context.get("strategy_key"),
        "step_index": strategy_context.get("step_index"),
        "strategy_context": strategy_context,
    }
    state.setdefault("submitted_orders", {})[order_no] = order_data
    _append_history(state, _history_from_submission(order_no, order_data))
    _save_state(state)
    _send_submission_notification(order_data)
    return order_data


def _holdings_to_map(holdings_df) -> Dict[str, Dict[str, Any]]:
    if holdings_df.empty:
        return {}
    mapped: Dict[str, Dict[str, Any]] = {}
    for _, row in holdings_df.iterrows():
        code = str(row.get("stock_code", ""))
        if not code:
            continue
        mapped[code] = {
            "stock_code": code,
            "stock_name": str(row.get("stock_name", code)),
            "quantity": int(row.get("quantity", 0) or 0),
            "avg_price": int(row.get("avg_price", 0) or 0),
        }
    return mapped


def _pending_to_map(pending_df) -> Dict[str, Dict[str, Any]]:
    if pending_df.empty:
        return {}
    mapped: Dict[str, Dict[str, Any]] = {}
    for _, row in pending_df.iterrows():
        order_no = str(row.get("order_no", ""))
        if not order_no:
            continue
        mapped[order_no] = {
            "order_no": order_no,
            "stock_code": str(row.get("stock_code", "")),
            "stock_name": str(row.get("stock_name", "")),
            "order_type": str(row.get("order_type", "")),
            "order_qty": int(row.get("order_qty", 0) or 0),
            "order_price": int(row.get("order_price", 0) or 0),
            "filled_qty": int(row.get("filled_qty", 0) or 0),
            "unfilled_qty": int(row.get("unfilled_qty", 0) or 0),
            "order_time": str(row.get("order_time", "")),
        }
    return mapped


def _estimate_fill_price(
    action: str,
    submitted: Dict[str, Any],
    prev_holding: Dict[str, Any] | None,
    curr_holding: Dict[str, Any] | None,
    filled_qty: int,
) -> int:
    if filled_qty <= 0:
        return int(submitted.get("price", 0) or 0)
    if action == "BUY" and curr_holding:
        curr_qty = int(curr_holding.get("quantity", 0) or 0)
        curr_avg = int(curr_holding.get("avg_price", 0) or 0)
        prev_qty = int((prev_holding or {}).get("quantity", 0) or 0)
        prev_avg = int((prev_holding or {}).get("avg_price", 0) or 0)
        if prev_qty > 0:
            estimated = round(((curr_avg * curr_qty) - (prev_avg * prev_qty)) / filled_qty)
            if estimated > 0:
                return estimated
        if curr_avg > 0:
            return curr_avg
    return int(submitted.get("price", 0) or 0)


def _build_fill_event(
    *,
    event_type: str,
    order_no: str,
    submitted: Dict[str, Any],
    filled_qty: int,
    fill_price: int,
    curr_holding: Dict[str, Any] | None,
    balance: Dict[str, Any],
    note: str,
    filled_total: int | None = None,
) -> Dict[str, Any]:
    avg_price_after = int((curr_holding or {}).get("avg_price", 0) or 0) or None
    event_suffix = filled_total if filled_total is not None else filled_qty
    return {
        "event_id": f"{event_type}:{order_no}:{event_suffix}",
        "event_type": event_type,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "order_no": order_no,
        "stock_code": submitted["stock_code"],
        "stock_name": submitted["stock_name"],
        "action": submitted["action"],
        "order_type": submitted["order_type"],
        "quantity": filled_qty,
        "price": fill_price,
        "step_index": submitted.get("step_index"),
        "strategy_key": submitted.get("strategy_key"),
        "avg_price_after": avg_price_after,
        "balance_after": int(balance.get("deposit", 0) or 0),
        "note": note,
    }


def _send_fill_notification(event: Dict[str, Any]) -> None:
    step_text = f"{event['step_index']}차 " if event.get("step_index") else ""
    action_label = "매수" if event["action"] == "BUY" else "매도"
    event_label = "체결" if event["event_type"] == "order_filled" else "부분 체결"
    avg_text = _format_price(event.get("avg_price_after"))
    balance_text = _format_balance({"deposit": event.get("balance_after")})
    message = "\n".join([
        f"[{event_label}] {step_text}{action_label}",
        f"종목: {event['stock_name']} ({event['stock_code']})",
        f"수량: {event['quantity']}주",
        f"체결가: {_format_price(event.get('price'))}",
        f"평단: {avg_text}",
        f"현잔액: {balance_text}",
        f"시각: {event['timestamp']}",
    ])
    send_message(message)


def sync_execution_state(env_dv: str = "real", force: bool = False) -> Dict[str, Any]:
    state = _load_state()
    now = datetime.now()
    last_synced_at = state.get("last_synced_at")
    if not force and last_synced_at:
        try:
            last_dt = datetime.fromisoformat(last_synced_at)
            if (now - last_dt).total_seconds() < SYNC_INTERVAL_SECONDS:
                return get_execution_snapshot(env_dv=env_dv, sync=False, state=state)
        except ValueError:
            pass

    holdings_df = get_holdings(env_dv)
    balance = get_deposit(env_dv) or {}
    pending_df, pending_ok = get_pending_orders(env_dv)
    reserved_df, reserved_ok = get_reserved_orders(env_dv)

    prev_holdings = state.get("holdings", {})
    prev_pending = state.get("pending_orders", {})
    submitted_orders = state.get("submitted_orders", {})
    current_holdings = _holdings_to_map(holdings_df)
    pending_frames = []
    if pending_ok and not pending_df.empty:
        pending_frames.append(pending_df)
    if reserved_ok and not reserved_df.empty:
        pending_frames.append(reserved_df)
    current_pending = _pending_to_map(pd.concat(pending_frames, ignore_index=True) if pending_frames else pd.DataFrame())

    new_events: List[Dict[str, Any]] = []

    for order_no, current in current_pending.items():
        previous = prev_pending.get(order_no)
        submitted = submitted_orders.get(order_no)
        if not previous or not submitted:
            continue
        prev_filled = int(previous.get("filled_qty", 0) or 0)
        curr_filled = int(current.get("filled_qty", 0) or 0)
        if curr_filled > prev_filled:
            delta = curr_filled - prev_filled
            curr_holding = current_holdings.get(submitted["stock_code"])
            fill_price = _estimate_fill_price(
                submitted["action"],
                submitted,
                prev_holdings.get(submitted["stock_code"]),
                curr_holding,
                delta,
            )
            event = _build_fill_event(
                event_type="partial_fill",
                order_no=order_no,
                submitted=submitted,
                filled_qty=delta,
                fill_price=fill_price,
                curr_holding=curr_holding,
                balance=balance,
                note="미체결 상태에서 일부 체결",
                filled_total=curr_filled,
            )
            _append_history(state, event)
            new_events.append(event)

    for order_no, previous in prev_pending.items():
        if order_no in current_pending:
            continue
        submitted = submitted_orders.get(order_no)
        if not submitted:
            continue
        stock_code = submitted["stock_code"]
        prev_holding = prev_holdings.get(stock_code)
        curr_holding = current_holdings.get(stock_code)
        prev_qty = int((prev_holding or {}).get("quantity", 0) or 0)
        curr_qty = int((curr_holding or {}).get("quantity", 0) or 0)
        delta = curr_qty - prev_qty if submitted["action"] == "BUY" else prev_qty - curr_qty

        if delta > 0:
            already_filled = int(previous.get("filled_qty", 0) or 0)
            event_type = "order_filled"
            fill_price = _estimate_fill_price(
                submitted["action"],
                submitted,
                prev_holding,
                curr_holding,
                delta,
            )
            event = _build_fill_event(
                event_type=event_type,
                order_no=order_no,
                submitted=submitted,
                filled_qty=delta,
                fill_price=fill_price,
                curr_holding=curr_holding,
                balance=balance,
                note="미체결 주문이 완료되어 체결 처리",
                filled_total=already_filled + delta,
            )
            _append_history(state, event)
            new_events.append(event)
            if submitted.get("strategy_key") and submitted["action"] == "SELL":
                if not curr_holding or int(curr_holding.get("quantity", 0) or 0) == 0:
                    clear_state(str(submitted["strategy_key"]), stock_code)
        else:
            cancel_event = {
                "event_id": f"closed:{order_no}",
                "event_type": "order_closed",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "order_no": order_no,
                "stock_code": submitted["stock_code"],
                "stock_name": submitted["stock_name"],
                "action": submitted["action"],
                "order_type": submitted["order_type"],
                "quantity": 0,
                "price": int(submitted.get("price", 0) or 0),
                "step_index": submitted.get("step_index"),
                "strategy_key": submitted.get("strategy_key"),
                "avg_price_after": int((curr_holding or {}).get("avg_price", 0) or 0) or None,
                "balance_after": int(balance.get("deposit", 0) or 0),
                "note": "미체결 주문이 종료되었지만 체결 수량 변화가 없어 알림 없이 기록만 남김",
            }
            _append_history(state, cancel_event)

    for event in new_events:
        _send_fill_notification(event)

    state["pending_orders"] = current_pending
    state["holdings"] = current_holdings
    state["balance"] = balance
    state["last_synced_at"] = now.isoformat()
    _save_state(state)
    return get_execution_snapshot(env_dv=env_dv, sync=False, state=state)


def get_execution_snapshot(
    env_dv: str = "real",
    sync: bool = True,
    state: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if sync:
        return sync_execution_state(env_dv=env_dv, force=False)

    state = state or _load_state()
    history = list(reversed(state.get("history", [])))
    cycle_states = load_cycle_states()
    holdings = state.get("holdings", {})

    latest_by_stock: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for item in history:
        key = (item.get("stock_code", ""), item.get("action", ""))
        latest_by_stock.setdefault(key, item)

    cycle_statuses = []
    for strategy_key, stock_bucket in cycle_states.items():
        for stock_code, cycle_state in stock_bucket.items():
            holding = holdings.get(stock_code, {})
            cycle_statuses.append({
                "strategy_key": strategy_key,
                "stock_code": stock_code,
                "stock_name": holding.get("stock_name", stock_code),
                "entry_count": int(cycle_state.get("entry_count", 0) or 0),
                "last_entry_price": int(cycle_state.get("last_entry_price", 0) or 0),
                "quantity": int(holding.get("quantity", 0) or 0),
                "avg_price": int(holding.get("avg_price", 0) or 0),
                "last_buy_price": int((latest_by_stock.get((stock_code, "BUY")) or {}).get("price", 0) or 0),
                "last_buy_quantity": int((latest_by_stock.get((stock_code, "BUY")) or {}).get("quantity", 0) or 0),
                "last_sell_price": int((latest_by_stock.get((stock_code, "SELL")) or {}).get("price", 0) or 0),
                "last_sell_quantity": int((latest_by_stock.get((stock_code, "SELL")) or {}).get("quantity", 0) or 0),
                "updated_at": cycle_state.get("updated_at"),
            })

    cycle_statuses.sort(key=lambda item: ((item.get("updated_at") or ""), item["stock_code"]), reverse=True)

    return {
        "status": "success",
        "history": history[:50],
        "cycle_statuses": cycle_statuses,
        "last_synced_at": state.get("last_synced_at"),
    }
