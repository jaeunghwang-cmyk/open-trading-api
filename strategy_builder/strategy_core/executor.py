"""
전략 실행기

4가지 실행 경로를 통합:
1. preset (class 있음) - 직접 인스턴스화
2. builder-only (class 없음, builder_state 있음) - DSL 변환 → 코드 생성 → 동적 실행
3. local_ (프런트에서 저장한 전략) - builder_state로 동적 실행
4. custom: (사용자 .py 파일) - 파일 동적 로드

모든 경로는 (code, name) → Signal → SignalResult로 변환되며,
결과를 log 콜백에 기록합니다.
"""

import importlib.util
import os
import re
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List

import pandas as pd

from core.cycle_reentry_state import clear_pending_order, clear_state, get_state
from core.data_fetcher import (
    get_current_price,
    get_daily_prices,
    get_pending_orders,
    get_reserved_orders,
)
from core.position_manager import PositionManager
from core.signal import Action, Signal
from strategy_core.dsl.converter import builder_state_to_dsl
from strategy_core.dsl.parser import parse_strategy
from strategy_core.dsl.codegen import StrategyCodeGenerator
from strategy_core.name_utils import sanitize_strategy_name


def execute_with_class(
    strategy_class,
    param_map: Dict[str, str],
    params: Dict[str, Any],
    stocks: List[str],
    strategy_id: str,
    log: Callable,
    get_stock_name: Callable,
    api_sleep: Callable,
) -> List[Dict]:
    """프리셋 전략 실행 (strategy_class가 있는 전략)

    Returns:
        SignalResult dict 리스트
    """
    # 파라미터 변환 (frontend key → backend key)
    converted_params = {}
    for frontend_key, backend_key in param_map.items():
        if frontend_key in params:
            converted_params[backend_key] = params[frontend_key]

    # consecutive 특수 처리
    if strategy_id == 'consecutive' and 'buy_days' in converted_params:
        converted_params['sell_days'] = converted_params['buy_days']

    log("info", f"파라미터: {converted_params}")

    strategy = strategy_class(**converted_params)
    return _run_strategy_on_stocks(strategy, stocks, log, get_stock_name, api_sleep)


def execute_from_builder_state(
    builder_state: Dict[str, Any],
    strategy_name: str,
    stocks: List[str],
    log: Callable,
    get_stock_name: Callable,
    api_sleep: Callable,
    env_dv: str = "real",
) -> List[Dict]:
    """BuilderState에서 전략 실행 (local_ 전략 및 builder-only 전략)

    Returns:
        SignalResult dict 리스트
    """
    log("info", f"빌더 전략: {strategy_name}")
    log("info", f"종목: {', '.join(stocks)}")

    cycle_reentry = (
        builder_state.get("positionManagement", {})
        .get("cycleReentry", {})
        .get("enabled", False)
    )
    if cycle_reentry:
        results = _run_cycle_reentry_on_stocks(
            builder_state=builder_state,
            strategy_name=strategy_name,
            stocks=stocks,
            log=log,
            get_stock_name=get_stock_name,
            api_sleep=api_sleep,
            env_dv=env_dv,
        )
        log("success", "반복 분할매수 사이클 전략 실행 완료")
        return results

    buy_condition, sell_condition = builder_state_to_dsl(builder_state)

    if not buy_condition:
        raise ValueError("매수 조건이 없습니다")

    log("info", f"매수 조건: {buy_condition}")
    if sell_condition:
        log("info", f"매도 조건: {sell_condition}")

    # DSL → AST → 코드 생성 → 동적 로드
    name_snake = sanitize_strategy_name(strategy_name)
    strategy_def = parse_strategy(
        name=name_snake,
        name_ko=strategy_name,
        buy_condition=buy_condition,
        sell_condition=sell_condition or "close < open",
    )

    generator = StrategyCodeGenerator()
    code = generator.generate(strategy_def)

    strategy_instance = _load_strategy_from_code(code, name_snake)
    results = _run_strategy_on_stocks(strategy_instance, stocks, log, get_stock_name, api_sleep)

    log("success", "빌더 전략 실행 완료")
    return results


def execute_custom_file(
    custom_name: str,
    strategy_dir: str,
    stocks: List[str],
    log: Callable,
    get_stock_name: Callable,
    api_sleep: Callable,
) -> List[Dict]:
    """커스텀 전략 실행 (사용자가 만든 .py 파일)

    Returns:
        SignalResult dict 리스트
    """
    log("info", f"커스텀 전략: {custom_name}")
    log("info", f"종목: {', '.join(stocks)}")

    # 경로 탐색 방어: 영숫자 + _ 만 허용
    if not re.fullmatch(r'[a-zA-Z0-9_]+', custom_name):
        raise ValueError(f"유효하지 않은 전략 이름: {custom_name!r}")

    strategy_file = Path(strategy_dir) / f"strategy_{custom_name}.py"

    # 부모 디렉터리 이탈 검사
    if not strategy_file.resolve().is_relative_to(Path(strategy_dir).resolve()):
        raise ValueError("허용되지 않는 전략 경로")

    if not strategy_file.exists():
        raise FileNotFoundError(f"전략 파일을 찾을 수 없습니다: {strategy_file}")

    spec = importlib.util.spec_from_file_location(f"strategy_{custom_name}", strategy_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    strategy_class = _find_strategy_class(module)
    if not strategy_class:
        raise ValueError("전략 클래스를 찾을 수 없습니다")

    strategy = strategy_class()
    results = _run_strategy_on_stocks(strategy, stocks, log, get_stock_name, api_sleep)

    log("success", "전략 실행 완료")
    return results


def _load_strategy_from_code(code: str, name_snake: str):
    """생성된 Python 코드를 동적으로 로드하여 전략 인스턴스 반환"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write(code)
        temp_file = f.name

    try:
        spec = importlib.util.spec_from_file_location(f"temp_strategy_{name_snake}", temp_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        strategy_class = _find_strategy_class(module)
        if not strategy_class:
            raise ValueError("전략 클래스를 생성할 수 없습니다")

        return strategy_class()
    finally:
        os.unlink(temp_file)


def _find_strategy_class(module):
    """모듈에서 Strategy 클래스 찾기"""
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and attr_name.endswith('Strategy') and attr_name != 'BaseStrategy':
            return attr
    return None


def _run_strategy_on_stocks(
    strategy,
    stocks: List[str],
    log: Callable,
    get_stock_name: Callable,
    api_sleep: Callable,
) -> List[Dict]:
    """전략을 종목 리스트에 대해 실행하고 결과 반환"""
    results = []

    for code in stocks:
        name = get_stock_name(code)
        log("info", f"분석 중: {name} ({code})")

        try:
            signal = strategy.generate_signal(code, name)
            result = {
                'code': code,
                'name': name,
                'action': signal.action.value.upper(),
                'strength': signal.strength,
                'reason': signal.reason,
                'target_price': getattr(signal, 'target_price', None),
                'quantity': getattr(signal, 'quantity', None),
                'strategy_context': getattr(signal, 'strategy_context', None),
            }
            results.append(result)

            action_icon = {"BUY": "▲", "SELL": "▼", "HOLD": "─"}
            action_type = {"BUY": "success", "SELL": "error", "HOLD": "info"}
            log(
                action_type.get(result['action'], "info"),
                f"  {action_icon.get(result['action'], '─')} {result['action']} | 강도: {result['strength']:.2f} | {result['reason']}"
            )
        except Exception as e:
            log("error", f"  오류: {str(e)}")
            results.append({
                'code': code,
                'name': name,
                'action': 'ERROR',
                'strength': 0,
                'reason': str(e),
                'target_price': None,
                'quantity': None,
                'strategy_context': None,
            })

        api_sleep()

    return results


def _run_cycle_reentry_on_stocks(
    builder_state: Dict[str, Any],
    strategy_name: str,
    stocks: List[str],
    log: Callable,
    get_stock_name: Callable,
    api_sleep: Callable,
    env_dv: str,
) -> List[Dict]:
    position_manager = PositionManager(env_dv=env_dv)
    holdings = position_manager.get_positions(refresh=True)
    pending_orders, pending_ok = get_pending_orders(env_dv)
    reserved_orders, reserved_ok = get_reserved_orders(env_dv)
    strategy_key = _get_cycle_strategy_key(builder_state, strategy_name)
    cycle_config = builder_state.get("positionManagement", {}).get("cycleReentry", {})

    merged_pending = []
    if pending_ok and not pending_orders.empty:
        merged_pending.append(pending_orders)
    if reserved_ok and not reserved_orders.empty:
        merged_pending.append(reserved_orders)
    all_pending_orders = pd.concat(merged_pending, ignore_index=True) if merged_pending else None

    results = []
    for code in stocks:
        name = get_stock_name(code)
        log("info", f"분석 중: {name} ({code})")

        try:
            signal = _generate_cycle_reentry_signal(
                stock_code=code,
                stock_name=name,
                strategy_key=strategy_key,
                cycle_config=cycle_config,
                holdings=holdings,
                pending_orders=all_pending_orders,
                env_dv=env_dv,
            )
            result = {
                "code": code,
                "name": name,
                "action": signal.action.value.upper(),
                "strength": signal.strength,
                "reason": signal.reason,
                "target_price": getattr(signal, "target_price", None),
                "quantity": getattr(signal, "quantity", None),
                "strategy_context": getattr(signal, "strategy_context", None),
            }
            results.append(result)

            action_icon = {"BUY": "▲", "SELL": "▼", "HOLD": "─"}
            action_type = {"BUY": "success", "SELL": "error", "HOLD": "info"}
            log(
                action_type.get(result["action"], "info"),
                f"  {action_icon.get(result['action'], '─')} {result['action']} | "
                f"수량: {result['quantity'] or 0} | {result['reason']}"
            )
        except Exception as e:
            log("error", f"  오류: {str(e)}")
            results.append({
                "code": code,
                "name": name,
                "action": "ERROR",
                "strength": 0,
                "reason": str(e),
                "target_price": None,
                "quantity": None,
                "strategy_context": None,
            })

        api_sleep()

    return results


def _generate_cycle_reentry_signal(
    stock_code: str,
    stock_name: str,
    strategy_key: str,
    cycle_config: Dict[str, Any],
    holdings,
    pending_orders,
    env_dv: str,
) -> Signal:
    split_count = max(1, int(cycle_config.get("splitCount", 1) or 1))
    base_amount = float(cycle_config.get("baseAmount", 0) or 0)
    drop_percent = float(cycle_config.get("dropPercent", 0) or 0)
    take_profit_percent = float(cycle_config.get("takeProfitPercent", 0) or 0)

    if base_amount <= 0:
        raise ValueError("반복 분할매수 사이클의 기준금액이 올바르지 않습니다.")

    tranche_amount = base_amount / split_count
    market_open = _is_kr_market_open()
    previous_close = _get_previous_close(stock_code, env_dv)
    current_quote = get_current_price(stock_code, env_dv)
    current_price = int(current_quote.get("price", 0) or 0)
    saved_state = get_state(strategy_key, stock_code)
    pending_order_id = str(saved_state.get("pending_order_id") or "").strip()

    if pending_orders is not None and not pending_orders.empty:
        stock_pending = pending_orders[pending_orders["stock_code"] == stock_code]
        if not stock_pending.empty:
            pending_qty = int(stock_pending["unfilled_qty"].sum())
            return Signal(
                stock_code=stock_code,
                stock_name=stock_name,
                action=Action.HOLD,
                strength=0.0,
                reason=f"미체결 주문 {pending_qty}주 대기 중",
            )

    if pending_order_id:
        pending_submitted_at = str(saved_state.get("pending_submitted_at") or "").strip()
        try:
            pending_dt = datetime.fromisoformat(pending_submitted_at)
        except ValueError:
            pending_dt = datetime.now()
        if datetime.now() - pending_dt < timedelta(minutes=15):
            return Signal(
                stock_code=stock_code,
                stock_name=stock_name,
                action=Action.HOLD,
                strength=0.0,
                reason="최근 접수한 주문의 체결/취소 여부 확인 대기 중",
            )
        clear_pending_order(strategy_key, stock_code)

    position = holdings[holdings["stock_code"] == stock_code] if not holdings.empty else holdings
    is_holding = not position.empty

    if not is_holding:
        clear_state(strategy_key, stock_code)
        entry_price = current_price if market_open else previous_close
        if entry_price <= 0:
            raise ValueError("진입 기준 가격을 조회하지 못했습니다.")
        quantity = int(tranche_amount // entry_price)
        if quantity <= 0:
            return Signal(
                stock_code=stock_code,
                stock_name=stock_name,
                action=Action.HOLD,
                strength=0.0,
                reason=f"1회 매수금액 {int(tranche_amount):,}원으로 1주도 매수할 수 없습니다.",
            )
        step_index = 1
        order_type = "market" if market_open else "limit"
        reason = (
            f"장중 1차 진입: 시가 진입 규칙에 따라 시장가 {quantity}주"
            if market_open
            else f"장전 1차 진입: 전일 종가 {entry_price:,}원에 {quantity}주 예약"
        )
        return _build_cycle_signal(
            stock_code=stock_code,
            stock_name=stock_name,
            action=Action.BUY,
            quantity=quantity,
            reason=reason,
            strategy_key=strategy_key,
            step_index=step_index,
            split_count=split_count,
            base_amount=base_amount,
            drop_percent=drop_percent,
            take_profit_percent=take_profit_percent,
            reference_price=entry_price,
            order_type=order_type,
            target_price=None if market_open else entry_price,
            strength=1.0 if market_open else 0.7,
        )

    avg_price = int(position.iloc[0].get("avg_price", 0) or 0)
    holding_qty = int(position.iloc[0].get("quantity", 0) or 0)
    if holding_qty <= 0 or avg_price <= 0:
        return Signal(
            stock_code=stock_code,
            stock_name=stock_name,
            action=Action.HOLD,
            strength=0.0,
            reason="보유 수량 또는 평단가를 확인하지 못했습니다.",
        )

    if pending_order_id:
        clear_pending_order(strategy_key, stock_code)
    saved_state = get_state(strategy_key, stock_code)
    last_entry_price = float(saved_state.get("last_entry_price") or avg_price)
    entry_count = int(saved_state.get("entry_count") or 0)
    if entry_count <= 0:
        estimated_count = int(round((avg_price * holding_qty) / tranche_amount)) if tranche_amount > 0 else 1
        entry_count = min(split_count, max(1, estimated_count))

    target_take_profit = avg_price * (1 + take_profit_percent / 100)
    if current_price > 0 and current_price >= target_take_profit:
        exit_price = current_price if market_open else previous_close
        if exit_price <= 0:
            exit_price = current_price or avg_price
        reason = (
            f"장중 익절: 평단 {avg_price:,}원 대비 +{take_profit_percent:g}% 도달로 전량 매도"
            if market_open
            else f"장전 익절: 전일 종가 {exit_price:,}원 기준 전량 매도 예약"
        )
        return _build_cycle_signal(
            stock_code=stock_code,
            stock_name=stock_name,
            action=Action.SELL,
            quantity=holding_qty,
            reason=reason,
            strategy_key=strategy_key,
            step_index=entry_count,
            split_count=split_count,
            base_amount=base_amount,
            drop_percent=drop_percent,
            take_profit_percent=take_profit_percent,
            reference_price=exit_price,
            order_type="market" if market_open else "limit",
            target_price=None if market_open else exit_price,
            strength=1.0 if market_open else 0.7,
        )

    if entry_count >= split_count:
        return Signal(
            stock_code=stock_code,
            stock_name=stock_name,
            action=Action.HOLD,
            strength=0.0,
            reason=f"최대 {split_count}회까지 모두 진입했습니다.",
        )

    trigger_price = last_entry_price * (1 - drop_percent / 100)
    if current_price <= 0 or current_price > trigger_price:
        return Signal(
            stock_code=stock_code,
            stock_name=stock_name,
            action=Action.HOLD,
            strength=0.0,
            reason=f"추가매수 대기: 마지막 매수가 {int(last_entry_price):,}원 대비 -{drop_percent:g}% 구간 미도달",
        )

    entry_price = current_price if market_open else previous_close
    if entry_price <= 0:
        raise ValueError("추가매수 기준 가격을 조회하지 못했습니다.")
    quantity = int(tranche_amount // entry_price)
    if quantity <= 0:
        return Signal(
            stock_code=stock_code,
            stock_name=stock_name,
            action=Action.HOLD,
            strength=0.0,
            reason=f"1회 매수금액 {int(tranche_amount):,}원으로 추가매수가 불가능합니다.",
        )
    next_step = entry_count + 1
    reason = (
        f"장중 {next_step}차 추가매수: 마지막 매수가 {int(last_entry_price):,}원 대비 -{drop_percent:g}% 하락"
        if market_open
        else f"장전 {next_step}차 추가매수: 전일 종가 {entry_price:,}원에 {quantity}주 예약"
    )
    return _build_cycle_signal(
        stock_code=stock_code,
        stock_name=stock_name,
        action=Action.BUY,
        quantity=quantity,
        reason=reason,
        strategy_key=strategy_key,
        step_index=next_step,
        split_count=split_count,
        base_amount=base_amount,
        drop_percent=drop_percent,
        take_profit_percent=take_profit_percent,
        reference_price=entry_price,
        order_type="market" if market_open else "limit",
        target_price=None if market_open else entry_price,
        strength=1.0 if market_open else 0.7,
    )


def _build_cycle_signal(
    stock_code: str,
    stock_name: str,
    action: Action,
    quantity: int,
    reason: str,
    strategy_key: str,
    step_index: int,
    split_count: int,
    base_amount: float,
    drop_percent: float,
    take_profit_percent: float,
    reference_price: int,
    order_type: str,
    target_price: int | None,
    strength: float,
) -> Signal:
    return Signal(
        stock_code=stock_code,
        stock_name=stock_name,
        action=action,
        strength=strength,
        reason=reason,
        target_price=target_price,
        quantity=quantity,
        strategy_context={
            "mode": "cycle_reentry",
            "strategy_key": strategy_key,
            "step_index": step_index,
            "split_count": split_count,
            "base_amount": base_amount,
            "drop_percent": drop_percent,
            "take_profit_percent": take_profit_percent,
            "reference_price": reference_price,
            "order_type": order_type,
            "reserve_order": order_type == "limit",
        },
    )


def _get_cycle_strategy_key(builder_state: Dict[str, Any], strategy_name: str) -> str:
    metadata = builder_state.get("metadata", {})
    raw_key = metadata.get("id") or metadata.get("name") or strategy_name
    return sanitize_strategy_name(str(raw_key))


def _get_previous_close(stock_code: str, env_dv: str) -> int:
    daily_prices = get_daily_prices(stock_code, days=2, env_dv=env_dv)
    if daily_prices.empty:
        return 0
    today = datetime.now().strftime("%Y%m%d")
    if len(daily_prices) >= 2 and str(daily_prices.iloc[-1].get("date", "")) == today:
        return int(daily_prices.iloc[-2].get("close", 0) or 0)
    return int(daily_prices.iloc[-1].get("close", 0) or 0)


def _is_kr_market_open(now: datetime | None = None) -> bool:
    now = now or datetime.now()
    if now.weekday() >= 5:
        return False
    current_time = now.time()
    return time(9, 0) <= current_time < time(15, 30)
