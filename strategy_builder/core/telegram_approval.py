"""
텔레그램 승인 주문 처리
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from core.data_fetcher import get_current_price
from core.position_manager import PositionManager
from core.telegram_notifier import get_updates, send_message


logger = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".kis_strategy_builder"
STATE_FILE = STATE_DIR / "telegram_approvals.json"
EXPIRY_MINUTES = 30


def _default_state() -> Dict[str, Any]:
    return {
        "pending": {},
        "last_update_id": 0,
    }


def get_pending_approval_count() -> int:
    state = _load_state()
    _purge_expired(state)
    return len(state.get("pending", {}))


def reset_update_offset() -> None:
    state = _load_state()
    state["last_update_id"] = 0
    _save_state(state)


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


def _purge_expired(state: Dict[str, Any]) -> None:
    now = datetime.now()
    expired = []
    for approval_id, payload in state.get("pending", {}).items():
        created_at = payload.get("created_at")
        if not created_at:
            continue
        try:
            created_dt = datetime.fromisoformat(created_at)
        except ValueError:
            expired.append(approval_id)
            continue
        if now - created_dt > timedelta(minutes=EXPIRY_MINUTES):
            expired.append(approval_id)
    for approval_id in expired:
        state["pending"].pop(approval_id, None)


def _build_order_request_from_signal(result: Dict[str, Any], env_dv: str) -> Dict[str, Any] | None:
    action = result.get("action")
    if action not in {"BUY", "SELL"}:
        return None

    stock_code = str(result.get("code", ""))
    stock_name = str(result.get("name", stock_code))
    strategy_context = result.get("strategy_context") or {}
    current_quote = get_current_price(stock_code, env_dv)
    current_price = int(current_quote.get("price", 0) or 0)
    target_price = int(result.get("target_price", 0) or 0)
    quantity = result.get("quantity")
    position_manager = PositionManager(env_dv=env_dv)

    if quantity is None:
        if action == "SELL":
            quantity = position_manager.get_holding_quantity(stock_code)
        else:
            quantity = 1
    quantity = int(quantity or 0)
    if quantity <= 0:
        return None

    price = target_price or current_price
    order_type = "limit" if target_price or strategy_context.get("reserve_order") else "market"

    return {
        "stock_code": stock_code,
        "stock_name": stock_name,
        "action": action,
        "order_type": order_type,
        "price": int(price or 0),
        "quantity": quantity,
        "signal_reason": str(result.get("reason", "")),
        "strategy_context": strategy_context,
    }


def queue_signal_approvals(results: List[Dict[str, Any]], env_dv: str) -> int:
    state = _load_state()
    _purge_expired(state)
    queued = 0

    for result in results:
        request = _build_order_request_from_signal(result, env_dv)
        if not request:
            continue
        approval_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{request['stock_code']}-{queued + 1}"
        state["pending"][approval_id] = {
            "created_at": datetime.now().isoformat(),
            "request": request,
        }
        action_label = "매수" if request["action"] == "BUY" else "매도"
        price_label = f"{request['price']:,}원" if request["price"] else "시장가"
        send_message(
            "\n".join([
                f"[시그널 발생] {action_label} 확인 필요",
                f"ID: {approval_id}",
                f"종목: {request['stock_name']} ({request['stock_code']})",
                f"수량: {request['quantity']}주",
                f"주문가: {price_label}",
                f"사유: {request['signal_reason']}",
                "",
                f"승인: /approve {approval_id}",
                f"거절: /reject {approval_id}",
            ])
        )
        queued += 1

    _save_state(state)
    return queued


async def process_telegram_approvals() -> None:
    state = _load_state()
    _purge_expired(state)
    offset = int(state.get("last_update_id", 0) or 0) + 1
    updates = get_updates(offset=offset, timeout=0)
    if not updates:
        _save_state(state)
        return

    for update in updates:
        state["last_update_id"] = max(int(state.get("last_update_id", 0) or 0), int(update.get("update_id", 0) or 0))
        message = update.get("message") or {}
        text = str(message.get("text", "")).strip()
        if not text:
            continue
        parsed = _parse_approval_command(text)
        if parsed is None:
            continue
        command, approval_id = parsed
        logger.info("텔레그램 승인 명령 수신: %s %s", command, approval_id)
        pending = state.get("pending", {}).get(approval_id)
        if not pending:
            send_message(f"승인 대기 주문을 찾을 수 없습니다: {approval_id}")
            continue

        if command == "/reject":
            state["pending"].pop(approval_id, None)
            send_message(f"주문 거절됨: {approval_id}")
            continue

        try:
            from backend.routers.orders import OrderRequest, execute_order_internal

            request = OrderRequest(**pending["request"])
            response = await execute_order_internal(request)
            if response.status == "success":
                send_message(f"주문 승인 및 접수 완료: {approval_id}")
            else:
                send_message(f"주문 승인 실패: {approval_id}\n사유: {response.message}")
        except Exception as exc:
            logger.exception("텔레그램 승인 주문 실행 실패")
            send_message(f"주문 승인 처리 중 오류: {approval_id}\n{exc}")
        finally:
            state["pending"].pop(approval_id, None)

    _save_state(state)


def _parse_approval_command(text: str) -> tuple[str, str] | None:
    parts = text.split()
    if len(parts) != 2:
        return None

    command = parts[0].strip().lower()
    approval_id = parts[1].strip()
    if "@" in command:
        command = command.split("@", 1)[0]

    if command not in {"/approve", "/reject"}:
        return None
    if not approval_id:
        return None
    return command, approval_id
