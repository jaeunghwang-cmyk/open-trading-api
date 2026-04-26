"use client";

import { useState, useEffect, useCallback } from "react";
import { Play, Loader2, Zap, Square, Radio } from "lucide-react";
import {
  StrategySelector,
  SignalList,
  OrderConfirmModal,
  HoldingsList,
  ExecutionLog,
  StockInput,
  OrderResultModal,
  CycleExecutionPanel,
} from "@/components/execute";
import { useAuth, useAccount, useStrategyExecutor, useOrder } from "@/hooks";
import {
  getCurrentPrice,
  getBuyableAmount,
  getPendingOrders,
  getExecutionHistory,
  cancelOrder,
  clearAccountCache,
  deleteExecutionHistory,
  clearExecutionHistory,
  getSignalRunnerStatus,
  startSignalRunner,
  stopSignalRunner,
  resetSignalRunnerPending,
  type PriceData,
  type PendingOrder,
  type ExecutionHistoryItem,
  type CycleStatusItem,
  type CancelOrderRequest,
  type SignalRunnerStatusResponse,
} from "@/lib/api";
import type { SignalResult } from "@/types/signal";
import type { OrderRequest, OrderResult } from "@/types/order";
import type { BuyableInfo } from "@/types/account";

export default function ExecutePage() {
  const { status: authStatus } = useAuth();
  const { holdings, balance, fetchHoldings, fetchBalance, resetThrottle, isLoading: accountLoading } = useAccount();
  const {
    strategies,
    selectedStrategy,
    params,
    signals,
    logs,
    isExecuting,
    error: strategyError,
    selectStrategy,
    setParam,
    execute,
    restoreExecutionState,
  } = useStrategyExecutor();
  const { execute: executeOrder, isLoading: orderLoading } = useOrder();

  const [stocks, setStocks] = useState<string[]>([]);
  const [selectedSignal, setSelectedSignal] = useState<SignalResult | null>(null);
  const [priceData, setPriceData] = useState<PriceData | null>(null);
  const [buyableInfo, setBuyableInfo] = useState<BuyableInfo | null>(null);
  const [sellableQty, setSellableQty] = useState<number | null>(null);
  const [showOrderModal, setShowOrderModal] = useState(false);

  // Order result modal state
  const [orderResult, setOrderResult] = useState<OrderResult | null>(null);
  const [orderInfo, setOrderInfo] = useState<{
    stock_name: string;
    stock_code: string;
    action: "BUY" | "SELL";
    quantity: number;
    price: number;
  } | null>(null);
  const [showResultModal, setShowResultModal] = useState(false);

  // Pending orders state
  const [pendingOrders, setPendingOrders] = useState<PendingOrder[]>([]);
  const [executionHistory, setExecutionHistory] = useState<ExecutionHistoryItem[]>([]);
  const [cycleStatuses, setCycleStatuses] = useState<CycleStatusItem[]>([]);
  const [executionSyncing, setExecutionSyncing] = useState(false);
  const [autoTradeEnabled, setAutoTradeEnabled] = useState(false);
  const [runnerStatus, setRunnerStatus] = useState<SignalRunnerStatusResponse | null>(null);
  const [runnerLoading, setRunnerLoading] = useState(false);
  const [runnerHydrated, setRunnerHydrated] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setAutoTradeEnabled(localStorage.getItem("kis_auto_trade_enabled") === "true");
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    localStorage.setItem("kis_auto_trade_enabled", String(autoTradeEnabled));
  }, [autoTradeEnabled]);

  const fetchPendingOrders = useCallback(async () => {
    try {
      const response = await getPendingOrders();
      if (response.status === "success") {
        setPendingOrders(response.orders || []);
      }
    } catch (error) {
      console.error("Failed to fetch pending orders:", error);
    }
  }, []);

  const fetchExecutionHistory = useCallback(async () => {
    setExecutionSyncing(true);
    try {
      const response = await getExecutionHistory();
      if (response.status === "success") {
        setExecutionHistory(response.history || []);
        setCycleStatuses(response.cycle_statuses || []);
      }
    } catch (error) {
      console.error("Failed to fetch execution history:", error);
    } finally {
      setExecutionSyncing(false);
    }
  }, []);

  const fetchRunnerStatus = useCallback(async () => {
    try {
      const response = await getSignalRunnerStatus();
      setRunnerStatus(response);
      return response;
    } catch (error) {
      console.error("Failed to fetch signal runner status:", error);
      return null;
    }
  }, []);

  // Fetch holdings, balance, and pending orders when authenticated
  // 순차 호출: 모의투자 모드의 초당 요청 제한 준수
  useEffect(() => {
    const fetchSequentially = async () => {
      await fetchHoldings();
      await fetchBalance();
      await fetchPendingOrders();
      await fetchExecutionHistory();
      await fetchRunnerStatus();
    };
    if (authStatus.authenticated) {
      fetchSequentially();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authStatus.authenticated, authStatus.mode, fetchRunnerStatus]);

  useEffect(() => {
    if (!authStatus.authenticated) {
      return;
    }
    const timer = setInterval(() => {
      fetchExecutionHistory();
      fetchRunnerStatus();
    }, 10000);
    return () => clearInterval(timer);
  }, [authStatus.authenticated, fetchExecutionHistory, fetchRunnerStatus]);

  const handleRefresh = useCallback(async () => {
    resetThrottle();
    await fetchHoldings();
    await fetchBalance();
    await fetchPendingOrders();
    await fetchExecutionHistory();
    await fetchRunnerStatus();
  }, [resetThrottle, fetchHoldings, fetchBalance, fetchPendingOrders, fetchExecutionHistory, fetchRunnerStatus]);

  useEffect(() => {
    if (!runnerStatus || !runnerStatus.session || strategies.length === 0 || runnerHydrated) {
      return;
    }

    const matched = strategies.find((strategy) => strategy.id === runnerStatus.session?.strategy_id);
    if (!matched) {
      return;
    }

    selectStrategy(matched);
    for (const [name, value] of Object.entries(runnerStatus.session.params || {})) {
      setParam(name, Number(value));
    }
    setStocks(runnerStatus.session.stocks || []);
    setAutoTradeEnabled(Boolean(runnerStatus.session.auto_trade));
    restoreExecutionState(runnerStatus.last_results || [], runnerStatus.last_logs || []);
    setRunnerHydrated(true);
  }, [runnerStatus, strategies, runnerHydrated, selectStrategy, setParam, restoreExecutionState]);

  useEffect(() => {
    if (!runnerStatus) {
      return;
    }
    if ((runnerStatus.last_results?.length || runnerStatus.last_logs?.length) && runnerStatus.last_run_at) {
      restoreExecutionState(runnerStatus.last_results || [], runnerStatus.last_logs || []);
    }
  }, [runnerStatus, restoreExecutionState]);

  const handleCancelOrder = useCallback(async (request: CancelOrderRequest) => {
    try {
      const response = await cancelOrder(request);
      if (response.success) {
        // 순차 호출: 취소 후 데이터 갱신
        await fetchPendingOrders();
        await fetchBalance();
      } else {
        alert(response.message || "주문 취소 실패");
      }
    } catch {
      alert("주문 취소 중 오류가 발생했습니다");
    }
  }, [fetchPendingOrders, fetchBalance]);

  const handleDeleteHistorySelected = useCallback(async (eventIds: string[]) => {
    if (eventIds.length === 0) {
      return;
    }
    if (!confirm(`선택한 ${eventIds.length}건의 주문/체결 이력을 삭제할까요?`)) {
      return;
    }
    try {
      await deleteExecutionHistory(eventIds);
      await fetchExecutionHistory();
    } catch {
      alert("주문/체결 이력 삭제 중 오류가 발생했습니다");
    }
  }, [fetchExecutionHistory]);

  const handleDeleteHistoryAll = useCallback(async () => {
    if (!confirm("최근 주문/체결 이력을 전체 삭제할까요?")) {
      return;
    }
    try {
      await clearExecutionHistory();
      await fetchExecutionHistory();
    } catch {
      alert("주문/체결 이력 전체 삭제 중 오류가 발생했습니다");
    }
  }, [fetchExecutionHistory]);

  const handleExecute = async () => {
    if (stocks.length === 0) {
      alert("종목을 입력해주세요");
      return;
    }
    const results = await execute(stocks, autoTradeEnabled);
    if (autoTradeEnabled && results.length > 0) {
      await executeSignalsImmediately(results);
    }
  };

  const handleStartRunner = async () => {
    if (!selectedStrategy || stocks.length === 0) {
      alert("전략과 종목을 먼저 설정해주세요");
      return;
    }
    setRunnerLoading(true);
    try {
      const response = await startSignalRunner(
        selectedStrategy.id,
        stocks,
        params,
        selectedStrategy.isLocal ? selectedStrategy.builder_state : undefined,
        autoTradeEnabled,
      );
      setRunnerStatus(response);
      setRunnerHydrated(true);
    } catch (error) {
      const message = error instanceof Error ? error.message : "시그널 시작 중 오류가 발생했습니다";
      alert(message);
    } finally {
      setRunnerLoading(false);
    }
  };

  const handleStopRunner = async () => {
    setRunnerLoading(true);
    try {
      const response = await stopSignalRunner();
      setRunnerStatus(response);
    } catch {
      alert("시그널 중지 중 오류가 발생했습니다");
    } finally {
      setRunnerLoading(false);
    }
  };

  const handleResetRunnerPending = async () => {
    if (stocks.length === 0) {
      alert("초기화할 종목이 없습니다");
      return;
    }
    if (!confirm("현재 종목들의 로컬 예약/미체결 대기 상태를 초기화할까요?\n실제 증권사 주문은 취소되지 않습니다.")) {
      return;
    }
    setRunnerLoading(true);
    try {
      const response = await resetSignalRunnerPending(stocks);
      alert(response.message);
      await fetchExecutionHistory();
      await fetchRunnerStatus();
    } catch (error) {
      const message = error instanceof Error ? error.message : "대기 상태 초기화 중 오류가 발생했습니다";
      alert(message);
    } finally {
      setRunnerLoading(false);
    }
  };

  const buildOrderRequestForSignal = useCallback(async (signal: SignalResult): Promise<OrderRequest | null> => {
    if (signal.action !== "BUY" && signal.action !== "SELL") {
      return null;
    }

    let currentPrice = signal.target_price ?? 0;
    try {
      const priceResponse = await getCurrentPrice(signal.code, authStatus.mode);
      if (priceResponse.status === "success" && priceResponse.data?.price) {
        currentPrice = priceResponse.data.price;
      }
    } catch {
      // Keep fallback price
    }

    const quantity =
      signal.quantity ??
      (signal.action === "SELL"
        ? (holdings.find((h) => h.stock_code === signal.code)?.quantity ?? 0)
        : 1);

    if (!quantity || quantity <= 0) {
      return null;
    }

    const reserveOrder = Boolean(signal.strategy_context?.reserve_order);
    const orderType = signal.target_price || reserveOrder ? "limit" : "market";

    return {
      stock_code: signal.code,
      stock_name: signal.name,
      action: signal.action,
      order_type: orderType,
      price: signal.target_price ?? currentPrice,
      quantity,
      signal_reason: signal.reason,
      strategy_context: signal.strategy_context,
    };
  }, [authStatus.mode, holdings]);

  const executeSignalsImmediately = useCallback(async (signalsToExecute: SignalResult[]) => {
    for (const signal of signalsToExecute) {
      if (signal.action !== "BUY" && signal.action !== "SELL") {
        continue;
      }
      const request = await buildOrderRequestForSignal(signal);
      if (!request) {
        continue;
      }
      await executeOrder(request);
    }
    await clearAccountCache();
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await handleRefresh();
  }, [buildOrderRequestForSignal, executeOrder, handleRefresh]);

  const handleSignalSelect = async (signal: SignalResult) => {
    setSelectedSignal(signal);

    // Only allow order for BUY/SELL signals
    if (signal.action === "BUY" || signal.action === "SELL") {
      // Fetch current price
      try {
        const priceResponse = await getCurrentPrice(signal.code, authStatus.mode);
        if (priceResponse.status === "success" && priceResponse.data) {
          setPriceData(priceResponse.data);
        } else {
          setPriceData(null);
        }

        // Fetch buyable amount for BUY signals; find holding quantity for SELL
        if (signal.action === "BUY") {
          const buyableResponse = await getBuyableAmount(
            signal.code,
            priceResponse.data?.price || 0
          );
          if (buyableResponse.status === "success" && buyableResponse.data) {
            setBuyableInfo(buyableResponse.data);
          } else {
            setBuyableInfo(null);
          }
          setSellableQty(null);
        } else {
          setBuyableInfo(null);
          const holding = holdings.find((h) => h.stock_code === signal.code);
          setSellableQty(holding?.quantity ?? null);
        }

        setShowOrderModal(true);
      } catch {
        setPriceData(null);
        setBuyableInfo(null);
        setSellableQty(null);
        setShowOrderModal(true);
      }
    }
  };

  const handleOrderConfirm = async (request: OrderRequest) => {
    const result = await executeOrder(request);

    // Store order info for result modal
    setOrderInfo({
      stock_name: request.stock_name,
      stock_code: request.stock_code,
      action: request.action,
      quantity: request.quantity,
      price: request.price || priceData?.price || 0,
    });
    setOrderResult(result);

    // Close order modal and show result modal
    setShowOrderModal(false);
    setSelectedSignal(null);
    setShowResultModal(true);

    // 백엔드 캐시 클리어 후 KIS API 반영 대기, 그 다음 프론트 갱신
    await clearAccountCache();
    await new Promise((r) => setTimeout(r, 1500));
    await handleRefresh();
  };

  const handleOrderCancel = () => {
    setShowOrderModal(false);
    setSelectedSignal(null);
    setBuyableInfo(null);
  };

  const handleResultModalClose = () => {
    setShowResultModal(false);
    setOrderResult(null);
    setOrderInfo(null);
  };

  return (
    <>
    <div className="max-w-7xl mx-auto px-4 py-6">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-display text-slate-900 dark:text-slate-100 flex items-center gap-3">
            <Zap className="w-7 h-7 text-primary" />
            전략 실행
          </h1>
          <p className="text-body text-slate-500 dark:text-slate-400 mt-1 ml-10">
            전략을 선택하고 종목에 적용하여 매매 시그널을 생성합니다
          </p>
        </div>

        {/* Auth Warning */}
        {!authStatus.authenticated && (
          <div className="card mb-6 border-yellow-200 dark:border-yellow-800 bg-yellow-50 dark:bg-yellow-900/20" role="alert">
            <p className="text-body text-yellow-800 dark:text-yellow-200">
              인증이 필요합니다. 우측 상단 설정에서 인증해주세요.
            </p>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left Panel - Strategy & Stocks */}
          <div className="lg:col-span-1 space-y-6">
            {/* Strategy Selector */}
            <div className="card p-6">
              <StrategySelector
                strategies={strategies}
                selectedStrategy={selectedStrategy}
                params={params}
                onSelect={selectStrategy}
                onParamChange={setParam}
              />
            </div>

            {/* Stock Input */}
            <div className="card p-6">
              <StockInput stocks={stocks} onChange={setStocks} />
            </div>

            {/* Execute Button */}
            <button
              onClick={handleExecute}
              disabled={!selectedStrategy || stocks.length === 0 || isExecuting || !authStatus.authenticated}
              className="w-full flex items-center justify-center gap-2 px-6 py-4 bg-primary text-white rounded-xl hover:bg-primary-dark disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium focus-ring"
              aria-label="시그널 생성"
            >
              {isExecuting ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  분석 중...
                </>
              ) : (
                <>
                  <Play className="w-5 h-5" />
                  시그널 생성
                </>
              )}
            </button>

            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={handleStartRunner}
                disabled={!selectedStrategy || stocks.length === 0 || runnerLoading || !authStatus.authenticated}
                className="flex items-center justify-center gap-2 px-4 py-3 bg-emerald-600 text-white rounded-xl hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium focus-ring"
              >
                {runnerLoading && !runnerStatus?.active ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Radio className="w-4 h-4" />
                )}
                시그널 시작
              </button>
              <button
                onClick={handleStopRunner}
                disabled={!runnerStatus?.active || runnerLoading}
                className="flex items-center justify-center gap-2 px-4 py-3 bg-slate-700 text-white rounded-xl hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium focus-ring"
              >
                {runnerLoading && Boolean(runnerStatus?.active) ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Square className="w-4 h-4" />
                )}
                시그널 중지
              </button>
            </div>

            <button
              onClick={handleResetRunnerPending}
              disabled={runnerLoading || stocks.length === 0 || !authStatus.authenticated}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-amber-50 text-amber-700 border border-amber-200 rounded-xl hover:bg-amber-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium focus-ring dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-900/40 dark:hover:bg-amber-900/30"
            >
              {runnerLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Square className="w-4 h-4" />
              )}
              대기 상태 초기화
            </button>

            <label className="flex items-center justify-center gap-2 text-sm text-slate-600 dark:text-slate-300">
              <input
                type="checkbox"
                checked={autoTradeEnabled}
                onChange={(e) => setAutoTradeEnabled(e.target.checked)}
                className="rounded border-slate-300 text-primary focus:ring-primary"
              />
              자동매매
            </label>

            <div className="card p-4 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">실행 상태</span>
                <span className={`text-xs px-2 py-1 rounded-full ${runnerStatus?.active ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300" : "bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300"}`}>
                  {runnerStatus?.active ? "실행 중" : "중지됨"}
                </span>
              </div>
              <div className="mt-3 space-y-1 text-xs text-slate-500 dark:text-slate-400">
                <p>실행 주기: 60초</p>
                <p>마지막 실행: {runnerStatus?.last_run_at ? new Date(runnerStatus.last_run_at).toLocaleString() : "-"}</p>
                <p>마지막 시작: {runnerStatus?.last_started_at ? new Date(runnerStatus.last_started_at).toLocaleString() : "-"}</p>
                {runnerStatus?.last_error && (
                  <p className="text-red-500">오류: {runnerStatus.last_error}</p>
                )}
              </div>
            </div>

            {strategyError && (
              <p className="text-caption text-red-500 text-center" role="alert">{strategyError}</p>
            )}
          </div>

          {/* Center Panel - Signals */}
          <div className="lg:col-span-1 space-y-6">
            <div className="card p-6">
              <h3 className="text-subheading mb-4">시그널 결과</h3>
              <SignalList
                signals={signals}
                onSelect={handleSignalSelect}
                selectedCode={selectedSignal?.code}
              />
            </div>

            {/* Execution Log */}
            {logs.length > 0 && (
              <ExecutionLog logs={logs} maxHeight="300px" />
            )}

            <CycleExecutionPanel
              statuses={cycleStatuses}
              history={executionHistory}
              isLoading={executionSyncing}
              onDeleteSelected={handleDeleteHistorySelected}
              onDeleteAll={handleDeleteHistoryAll}
            />
          </div>

          {/* Right Panel - Holdings */}
          <div className="lg:col-span-1">
            <HoldingsList
              holdings={holdings}
              pendingOrders={pendingOrders}
              balance={balance}
              onRefresh={handleRefresh}
              onCancelOrder={handleCancelOrder}
              isLoading={accountLoading}
            />
          </div>
        </div>
      </div>

      {/* Order Confirmation Modal */}
      {showOrderModal && selectedSignal && (
        <OrderConfirmModal
          signal={selectedSignal}
          priceData={priceData}
          buyable={buyableInfo}
          sellableQty={sellableQty}
          onConfirm={handleOrderConfirm}
          onCancel={handleOrderCancel}
          isLoading={orderLoading}
        />
      )}

      {/* Order Result Modal */}
      {showResultModal && orderResult && orderInfo && (
        <OrderResultModal
          result={orderResult}
          orderInfo={orderInfo}
          onClose={handleResultModalClose}
        />
      )}
    </>
  );
}
