"use client";

import { useMemo, useState, type ReactNode } from "react";
import { Activity, Clock3, Repeat, Trash2, Wallet, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CycleStatusItem, ExecutionHistoryItem } from "@/lib/api";

interface CycleExecutionPanelProps {
  statuses: CycleStatusItem[];
  history: ExecutionHistoryItem[];
  isLoading?: boolean;
  onDeleteSelected?: (eventIds: string[]) => Promise<void> | void;
  onDeleteAll?: () => Promise<void> | void;
}

export function CycleExecutionPanel({
  statuses,
  history,
  isLoading,
  onDeleteSelected,
  onDeleteAll,
}: CycleExecutionPanelProps) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const allSelected = useMemo(
    () => history.length > 0 && selectedIds.length === history.length,
    [history.length, selectedIds.length],
  );

  const toggleItem = (eventId: string) => {
    setSelectedIds((prev) =>
      prev.includes(eventId) ? prev.filter((id) => id !== eventId) : [...prev, eventId],
    );
  };

  const toggleAll = () => {
    setSelectedIds(allSelected ? [] : history.map((item) => item.event_id));
  };

  const handleDeleteSelected = async () => {
    if (selectedIds.length === 0 || !onDeleteSelected) return;
    await onDeleteSelected(selectedIds);
    setSelectedIds([]);
  };

  const handleDeleteAll = async () => {
    if (!onDeleteAll) return;
    await onDeleteAll();
    setSelectedIds([]);
  };

  const clearSelection = () => setSelectedIds([]);

  return (
    <div className="card p-6 space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-subheading flex items-center gap-2">
            <Repeat className="w-5 h-5 text-primary" />
            사이클 실행 현황
          </h3>
          <p className="text-xs text-slate-500 mt-1">
            차수, 최근 주문/체결, 평단과 잔액 추적
          </p>
        </div>
        {isLoading && <span className="text-xs text-slate-400">동기화 중...</span>}
      </div>

      <div className="space-y-3">
        {statuses.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-200 dark:border-slate-700 p-4 text-sm text-slate-500">
            활성화된 반복 분할매수 상태가 없습니다.
          </div>
        ) : (
          statuses.map((status) => (
            <div
              key={`${status.strategy_key}-${status.stock_code}`}
              className="rounded-xl border border-slate-200 dark:border-slate-700 p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-medium text-slate-900 dark:text-slate-100">
                    {status.stock_name}
                  </div>
                  <div className="text-xs text-slate-400 font-mono">
                    {status.stock_code} · {status.strategy_key}
                  </div>
                </div>
                <span className="px-2 py-1 rounded-full text-xs font-medium bg-primary/10 text-primary">
                  {status.entry_count}차
                </span>
              </div>

              <div className="grid grid-cols-2 gap-3 mt-3 text-sm">
                <Metric label="보유수량" value={`${status.quantity.toLocaleString()}주`} />
                <Metric label="평단" value={`${status.avg_price.toLocaleString()}원`} />
                <Metric label="마지막 매수" value={status.last_buy_price ? `${status.last_buy_price.toLocaleString()}원 / ${status.last_buy_quantity}주` : "-"} />
                <Metric label="마지막 기준가" value={status.last_entry_price ? `${status.last_entry_price.toLocaleString()}원` : "-"} />
                <Metric label="마지막 매도" value={status.last_sell_price ? `${status.last_sell_price.toLocaleString()}원 / ${status.last_sell_quantity}주` : "-"} />
                <Metric label="업데이트" value={status.updated_at ? status.updated_at.replace("T", " ").slice(5, 16) : "-"} />
              </div>
            </div>
          ))
        )}
      </div>

      <div>
        <div className="flex items-center justify-between gap-3 mb-3">
          <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-2">
            <Activity className="w-4 h-4" />
            최근 주문/체결
          </h4>
          {history.length > 0 ? (
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-2 text-xs text-slate-500">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                  className="rounded border-slate-300 text-primary focus:ring-primary"
                />
                전체선택
              </label>
              <button
                type="button"
                onClick={handleDeleteSelected}
                disabled={selectedIds.length === 0}
                className="inline-flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-700 px-2.5 py-1.5 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50"
              >
                <Trash2 className="w-3.5 h-3.5" />
                선택 삭제
              </button>
              <button
                type="button"
                onClick={handleDeleteAll}
                className="inline-flex items-center gap-1 rounded-lg border border-red-200 dark:border-red-900/50 px-2.5 py-1.5 text-xs text-red-600 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-950/30"
              >
                <Trash2 className="w-3.5 h-3.5" />
                전체 삭제
              </button>
              {selectedIds.length > 0 ? (
                <button
                  type="button"
                  onClick={clearSelection}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 dark:border-slate-700 px-2.5 py-1.5 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800"
                >
                  <X className="w-3.5 h-3.5" />
                  선택 해제
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="space-y-2 max-h-[360px] overflow-auto">
          {history.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-200 dark:border-slate-700 p-4 text-sm text-slate-500">
              아직 기록이 없습니다.
            </div>
          ) : (
            history.map((item) => {
              const isBuy = item.action === "BUY";
              const label = getEventLabel(item);
              return (
                <div
                  key={item.event_id}
                  className="rounded-xl border border-slate-200 dark:border-slate-700 p-3"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        checked={selectedIds.includes(item.event_id)}
                        onChange={() => toggleItem(item.event_id)}
                        className="mt-1 rounded border-slate-300 text-primary focus:ring-primary"
                      />
                      <div>
                        <div className="flex items-center gap-2">
                          <span
                            className={cn(
                              "text-xs px-2 py-0.5 rounded-full font-medium",
                              isBuy
                                ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                                : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                            )}
                          >
                            {label}
                          </span>
                          <span className="font-medium">{item.stock_name}</span>
                          {item.step_index ? (
                            <span className="text-xs text-primary">{item.step_index}차</span>
                          ) : null}
                        </div>
                        <div className="text-xs text-slate-400 font-mono mt-1">
                          {item.stock_code} · 주문번호 {item.order_no}
                        </div>
                      </div>
                    </div>
                    <div className="text-xs text-slate-500 flex items-center gap-1">
                      <Clock3 className="w-3 h-3" />
                      {item.timestamp.slice(5)}
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2 mt-3 text-sm">
                    <Metric label="수량" value={`${item.quantity.toLocaleString()}주`} />
                    <Metric label="가격" value={`${item.price.toLocaleString()}원`} />
                    <Metric label="평단" value={item.avg_price_after ? `${item.avg_price_after.toLocaleString()}원` : "-"} />
                    <Metric
                      label="현잔액"
                      value={
                        item.balance_after != null ? `${item.balance_after.toLocaleString()}원` : "-"
                      }
                      icon={<Wallet className="w-3 h-3" />}
                    />
                  </div>

                  {item.note ? (
                    <div className="text-xs text-slate-500 mt-2">{item.note}</div>
                  ) : null}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon?: ReactNode;
}) {
  return (
    <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 px-3 py-2">
      <div className="text-xs text-slate-500 flex items-center gap-1">
        {icon}
        {label}
      </div>
      <div className="font-medium text-slate-900 dark:text-slate-100 mt-1">{value}</div>
    </div>
  );
}

function getEventLabel(item: ExecutionHistoryItem): string {
  if (item.event_type === "order_submitted") {
    const actionLabel = item.action === "BUY" ? "매수" : "매도";
    return item.order_type === "reserve" ? `예약 ${actionLabel}` : `${actionLabel} 접수`;
  }
  if (item.event_type === "partial_fill") {
    return item.action === "BUY" ? "매수 부분체결" : "매도 부분체결";
  }
  if (item.event_type === "order_filled") {
    return item.action === "BUY" ? "매수 체결" : "매도 체결";
  }
  return "주문 종료";
}
