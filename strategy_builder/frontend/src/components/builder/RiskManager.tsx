"use client";

import { useCallback } from "react";
import { Shield, TrendingDown, TrendingUp, Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  EntrySplitStep,
  ExitSplitStep,
  PositionManagement,
  RiskManagement,
} from "@/types/builder";

interface RiskManagerProps {
  risk: RiskManagement & { positionManagement?: PositionManagement };
  onChange: (updates: Partial<RiskManagement> & { positionManagement?: PositionManagement }) => void;
}

export function RiskManager({ risk, onChange }: RiskManagerProps) {
  const positionManagement = risk.positionManagement ?? {
    splitEntriesEnabled: false,
    splitExitsEnabled: false,
    entrySteps: [
      { id: "entry_step_1", enabled: true, allocationPercent: 100, trigger: "signal" as const },
      { id: "entry_step_2", enabled: false, allocationPercent: 0, trigger: "additional_drop_pct" as const, dropPercent: 3 },
      { id: "entry_step_3", enabled: false, allocationPercent: 0, trigger: "additional_drop_pct" as const, dropPercent: 6 },
      { id: "entry_step_4", enabled: false, allocationPercent: 0, trigger: "additional_drop_pct" as const, dropPercent: 9 },
      { id: "entry_step_5", enabled: false, allocationPercent: 0, trigger: "additional_drop_pct" as const, dropPercent: 12 },
    ],
    exitSteps: [
      { id: "exit_step_1", enabled: true, allocationPercent: 100, trigger: "exit_signal" as const },
      { id: "exit_step_2", enabled: false, allocationPercent: 0, trigger: "take_profit_pct" as const, targetPercent: 5 },
    ],
    cycleReentry: {
      enabled: false,
      baseAmount: 5_000_000,
      splitCount: 5,
      dropPercent: 5,
      takeProfitPercent: 3,
    },
  };

  const handleStopLossToggle = useCallback(() => {
    onChange({
      stopLoss: {
        ...risk.stopLoss,
        enabled: !risk.stopLoss.enabled,
      },
    });
  }, [onChange, risk.stopLoss]);

  const handleStopLossChange = useCallback(
    (percent: number) => {
      onChange({
        stopLoss: {
          ...risk.stopLoss,
          percent,
        },
      });
    },
    [onChange, risk.stopLoss]
  );

  const handleTakeProfitToggle = useCallback(() => {
    onChange({
      takeProfit: {
        ...risk.takeProfit,
        enabled: !risk.takeProfit.enabled,
      },
    });
  }, [onChange, risk.takeProfit]);

  const handleTakeProfitChange = useCallback(
    (percent: number) => {
      onChange({
        takeProfit: {
          ...risk.takeProfit,
          percent,
        },
      });
    },
    [onChange, risk.takeProfit]
  );

  const handleTrailingStopToggle = useCallback(() => {
    onChange({
      trailingStop: {
        ...risk.trailingStop,
        enabled: !risk.trailingStop.enabled,
      },
    });
  }, [onChange, risk.trailingStop]);

  const handleTrailingStopChange = useCallback(
    (percent: number) => {
      onChange({
        trailingStop: {
          ...risk.trailingStop,
          percent,
        },
      });
    },
    [onChange, risk.trailingStop]
  );

  const updatePositionManagement = useCallback((updates: Partial<PositionManagement>) => {
    onChange({
      positionManagement: {
        ...positionManagement,
        ...updates,
      },
    });
  }, [onChange, positionManagement]);

  const updateEntryStep = useCallback((id: string, updates: Partial<EntrySplitStep>) => {
    updatePositionManagement({
      entrySteps: positionManagement.entrySteps.map((step) =>
        step.id === id ? { ...step, ...updates } : step
      ),
    });
  }, [positionManagement.entrySteps, updatePositionManagement]);

  const updateExitStep = useCallback((id: string, updates: Partial<ExitSplitStep>) => {
    updatePositionManagement({
      exitSteps: positionManagement.exitSteps.map((step) =>
        step.id === id ? { ...step, ...updates } : step
      ),
    });
  }, [positionManagement.exitSteps, updatePositionManagement]);

  return (
    <div className="space-y-4">
      <RiskItem
        id="stop-loss"
        icon={<TrendingDown className="w-4 h-4" />}
        title="손절 (Stop Loss)"
        description="손실이 설정값에 도달하면 자동 청산"
        enabled={risk.stopLoss.enabled}
        percent={risk.stopLoss.percent}
        onToggle={handleStopLossToggle}
        onChange={handleStopLossChange}
        color="red"
      />

      <RiskItem
        id="take-profit"
        icon={<TrendingUp className="w-4 h-4" />}
        title="익절 (Take Profit)"
        description="수익이 설정값에 도달하면 자동 청산"
        enabled={risk.takeProfit.enabled}
        percent={risk.takeProfit.percent}
        onToggle={handleTakeProfitToggle}
        onChange={handleTakeProfitChange}
        color="green"
      />

      <RiskItem
        id="trailing-stop"
        icon={<Activity className="w-4 h-4" />}
        title="트레일링 스탑"
        description="고점 대비 설정값 하락 시 자동 청산"
        enabled={risk.trailingStop.enabled}
        percent={risk.trailingStop.percent}
        onToggle={handleTrailingStopToggle}
        onChange={handleTrailingStopChange}
        color="blue"
      />

      <SplitSection
        title="반복 분할매수 사이클"
        description="기준금액을 N분할해 시가 진입하고, 마지막 매수가 대비 -A%마다 같은 금액으로 추가매수한 뒤 평단 기준 +B% 수익 시 전량 매도 후 다음 사이클을 다시 시작합니다."
        enabled={positionManagement.cycleReentry.enabled}
        onToggle={() =>
          updatePositionManagement({
            cycleReentry: {
              ...positionManagement.cycleReentry,
              enabled: !positionManagement.cycleReentry.enabled,
            },
          })
        }
      >
        <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3 space-y-3">
          <div className="grid grid-cols-4 gap-2">
            <label className="text-xs text-slate-500">
              기준금액
              <input
                type="number"
                min={1}
                step={10000}
                value={positionManagement.cycleReentry.baseAmount}
                onChange={(e) =>
                  updatePositionManagement({
                    cycleReentry: {
                      ...positionManagement.cycleReentry,
                      baseAmount: Math.max(1, parseFloat(e.target.value) || 1),
                    },
                  })
                }
                className="mt-1 w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-700 rounded bg-white dark:bg-slate-800"
              />
            </label>
            <label className="text-xs text-slate-500">
              분할 횟수
              <input
                type="number"
                min={1}
                max={10}
                step={1}
                value={positionManagement.cycleReentry.splitCount}
                onChange={(e) =>
                  updatePositionManagement({
                    cycleReentry: {
                      ...positionManagement.cycleReentry,
                      splitCount: Math.max(1, parseInt(e.target.value, 10) || 1),
                    },
                  })
                }
                className="mt-1 w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-700 rounded bg-white dark:bg-slate-800"
              />
            </label>
            <label className="text-xs text-slate-500">
              추가매수 A%
              <input
                type="number"
                min={0.1}
                max={100}
                step={0.1}
                value={positionManagement.cycleReentry.dropPercent}
                onChange={(e) =>
                  updatePositionManagement({
                    cycleReentry: {
                      ...positionManagement.cycleReentry,
                      dropPercent: Math.max(0.1, parseFloat(e.target.value) || 0.1),
                    },
                  })
                }
                className="mt-1 w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-700 rounded bg-white dark:bg-slate-800"
              />
            </label>
            <label className="text-xs text-slate-500">
              익절 B%
              <input
                type="number"
                min={0.1}
                max={100}
                step={0.1}
                value={positionManagement.cycleReentry.takeProfitPercent}
                onChange={(e) =>
                  updatePositionManagement({
                    cycleReentry: {
                      ...positionManagement.cycleReentry,
                      takeProfitPercent: Math.max(0.1, parseFloat(e.target.value) || 0.1),
                    },
                  })
                }
                className="mt-1 w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-700 rounded bg-white dark:bg-slate-800"
              />
            </label>
          </div>
          <div className="text-xs text-slate-500">
            1회 매수금액은 <span className="font-medium text-slate-700 dark:text-slate-200">
              {Math.round(positionManagement.cycleReentry.baseAmount / Math.max(1, positionManagement.cycleReentry.splitCount)).toLocaleString()}원
            </span>
            입니다.
          </div>
        </div>
      </SplitSection>

      <SplitSection
        title="분할 매수"
        description="진입 신호 후 추가 하락 구간을 나눠서 비중별 진입합니다."
        enabled={positionManagement.splitEntriesEnabled}
        onToggle={() =>
          updatePositionManagement({ splitEntriesEnabled: !positionManagement.splitEntriesEnabled })
        }
      >
        {positionManagement.entrySteps.map((step, index) => (
          <EntrySplitEditor
            key={step.id}
            label={`${index + 1}차 매수`}
            step={step}
            onChange={(updates) => updateEntryStep(step.id, updates)}
          />
        ))}
      </SplitSection>

      <SplitSection
        title="분할 매도"
        description="청산 신호 외에 익절·손절·보유기간 기준으로 부분 청산할 수 있습니다."
        enabled={positionManagement.splitExitsEnabled}
        onToggle={() =>
          updatePositionManagement({ splitExitsEnabled: !positionManagement.splitExitsEnabled })
        }
      >
        {positionManagement.exitSteps.map((step, index) => (
          <ExitSplitEditor
            key={step.id}
            label={`${index + 1}차 매도`}
            step={step}
            onChange={(updates) => updateExitStep(step.id, updates)}
          />
        ))}
      </SplitSection>

      {/* Info */}
      <div className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
        <div className="flex items-start gap-2">
          <Shield className="w-4 h-4 text-slate-400 mt-0.5" aria-hidden="true" />
          <div className="text-xs text-slate-500">
            <p>리스크 관리 설정은 백테스트 시 적용됩니다.</p>
            <p className="mt-1">손절/익절은 진입가 대비 %, 트레일링 스탑은 최고점 대비 %입니다.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

interface SplitSectionProps {
  title: string;
  description: string;
  enabled: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

function SplitSection({ title, description, enabled, onToggle, children }: SplitSectionProps) {
  return (
    <div className="p-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="font-medium text-sm text-slate-900 dark:text-white">{title}</div>
          <div className="text-xs text-slate-500 mt-1">{description}</div>
        </div>
        <input
          type="checkbox"
          checked={enabled}
          onChange={onToggle}
          className="toggle-switch toggle-blue"
          role="switch"
          aria-checked={enabled}
          aria-label={title}
        />
      </div>
      {enabled && <div className="space-y-3 mt-3">{children}</div>}
    </div>
  );
}

interface EntrySplitEditorProps {
  label: string;
  step: EntrySplitStep;
  onChange: (updates: Partial<EntrySplitStep>) => void;
}

function EntrySplitEditor({ label, step, onChange }: EntrySplitEditorProps) {
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium text-slate-900 dark:text-white">{label}</div>
        <input
          type="checkbox"
          checked={step.enabled}
          onChange={() => onChange({ enabled: !step.enabled })}
          className="toggle-switch toggle-green"
          role="switch"
          aria-checked={step.enabled}
          aria-label={label}
        />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-slate-500">
          비중 %
          <input
            type="number"
            min={0}
            max={100}
            step={1}
            value={step.allocationPercent}
            onChange={(e) => onChange({ allocationPercent: parseFloat(e.target.value) || 0 })}
            className="mt-1 w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-700 rounded bg-white dark:bg-slate-800"
          />
        </label>
        <label className="text-xs text-slate-500">
          트리거
          <select
            value={step.trigger}
            onChange={(e) => onChange({ trigger: e.target.value as EntrySplitStep["trigger"] })}
            className="mt-1 w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-700 rounded bg-white dark:bg-slate-800"
          >
            <option value="signal">진입 신호</option>
            <option value="additional_drop_pct">추가 하락 %</option>
          </select>
        </label>
      </div>
      {step.trigger === "additional_drop_pct" && (
        <label className="text-xs text-slate-500 block">
          이전 매수가 대비 추가 하락 %
          <input
            type="number"
            min={0}
            max={100}
            step={0.1}
            value={step.dropPercent ?? 0}
            onChange={(e) => onChange({ dropPercent: parseFloat(e.target.value) || 0 })}
            className="mt-1 w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-700 rounded bg-white dark:bg-slate-800"
          />
        </label>
      )}
    </div>
  );
}

interface ExitSplitEditorProps {
  label: string;
  step: ExitSplitStep;
  onChange: (updates: Partial<ExitSplitStep>) => void;
}

function ExitSplitEditor({ label, step, onChange }: ExitSplitEditorProps) {
  const needsTarget =
    step.trigger === "take_profit_pct" ||
    step.trigger === "stop_loss_pct" ||
    step.trigger === "trailing_stop_pct";

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-700 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium text-slate-900 dark:text-white">{label}</div>
        <input
          type="checkbox"
          checked={step.enabled}
          onChange={() => onChange({ enabled: !step.enabled })}
          className="toggle-switch toggle-red"
          role="switch"
          aria-checked={step.enabled}
          aria-label={label}
        />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-slate-500">
          비중 %
          <input
            type="number"
            min={0}
            max={100}
            step={1}
            value={step.allocationPercent}
            onChange={(e) => onChange({ allocationPercent: parseFloat(e.target.value) || 0 })}
            className="mt-1 w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-700 rounded bg-white dark:bg-slate-800"
          />
        </label>
        <label className="text-xs text-slate-500">
          트리거
          <select
            value={step.trigger}
            onChange={(e) => onChange({ trigger: e.target.value as ExitSplitStep["trigger"] })}
            className="mt-1 w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-700 rounded bg-white dark:bg-slate-800"
          >
            <option value="exit_signal">청산 신호</option>
            <option value="take_profit_pct">익절 %</option>
            <option value="stop_loss_pct">손절 %</option>
            <option value="trailing_stop_pct">트레일링 %</option>
            <option value="hold_days">보유일수</option>
          </select>
        </label>
      </div>
      {needsTarget && (
        <label className="text-xs text-slate-500 block">
          목표 %
          <input
            type="number"
            min={0}
            max={100}
            step={0.1}
            value={step.targetPercent ?? 0}
            onChange={(e) => onChange({ targetPercent: parseFloat(e.target.value) || 0 })}
            className="mt-1 w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-700 rounded bg-white dark:bg-slate-800"
          />
        </label>
      )}
      {step.trigger === "hold_days" && (
        <label className="text-xs text-slate-500 block">
          보유일수
          <input
            type="number"
            min={1}
            max={365}
            step={1}
            value={step.holdDays ?? 1}
            onChange={(e) => onChange({ holdDays: parseInt(e.target.value, 10) || 1 })}
            className="mt-1 w-full px-2 py-1 text-sm border border-slate-200 dark:border-slate-700 rounded bg-white dark:bg-slate-800"
          />
        </label>
      )}
    </div>
  );
}

// ============================================================
// Risk Item Component - Semantic HTML
// ============================================================

interface RiskItemProps {
  id: string;
  icon: React.ReactNode;
  title: string;
  description: string;
  enabled: boolean;
  percent: number;
  onToggle: () => void;
  onChange: (percent: number) => void;
  color: "red" | "green" | "blue";
}

function RiskItem({
  id,
  icon,
  title,
  description,
  enabled,
  percent,
  onToggle,
  onChange,
  color,
}: RiskItemProps) {
  const colorClasses = {
    red: {
      bg: "bg-red-50 dark:bg-red-900/20",
      border: "border-red-200 dark:border-red-800",
      icon: "text-red-500",
      toggle: "toggle-red",
      range: "range-red",
    },
    green: {
      bg: "bg-green-50 dark:bg-green-900/20",
      border: "border-green-200 dark:border-green-800",
      icon: "text-green-500",
      toggle: "toggle-green",
      range: "range-green",
    },
    blue: {
      bg: "bg-blue-50 dark:bg-blue-900/20",
      border: "border-blue-200 dark:border-blue-800",
      icon: "text-blue-500",
      toggle: "toggle-blue",
      range: "range-blue",
    },
  };

  const toggleId = `toggle-${id}`;
  const sliderId = `slider-${id}`;
  const numberId = `number-${id}`;

  return (
    <div
      className={cn(
        "p-3 rounded-lg border transition-colors",
        enabled ? colorClasses[color].bg : "bg-slate-50 dark:bg-slate-800/50",
        enabled ? colorClasses[color].border : "border-slate-200 dark:border-slate-700"
      )}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={cn(enabled ? colorClasses[color].icon : "text-slate-400")} aria-hidden="true">
            {icon}
          </span>
          <label
            htmlFor={toggleId}
            className="font-medium text-sm text-slate-900 dark:text-white cursor-pointer"
          >
            {title}
          </label>
        </div>
        {/* Semantic toggle: checkbox with CSS styling */}
        <input
          type="checkbox"
          id={toggleId}
          checked={enabled}
          onChange={onToggle}
          className={cn("toggle-switch", colorClasses[color].toggle)}
          aria-label={`${title} ${enabled ? "활성화됨" : "비활성화됨"}`}
          role="switch"
          aria-checked={enabled}
        />
      </div>

      <p className="text-xs text-slate-500 mb-2">{description}</p>

      {enabled && (
        <div className="flex items-center gap-2">
          <label htmlFor={sliderId} className="sr-only">{title} 퍼센트 슬라이더</label>
          <input
            id={sliderId}
            type="range"
            min={1}
            max={50}
            step={0.5}
            value={percent}
            onChange={(e) => onChange(parseFloat(e.target.value))}
            className={cn("flex-1", colorClasses[color].range)}
            aria-valuemin={1}
            aria-valuemax={50}
            aria-valuenow={percent}
            aria-label={`${title} 퍼센트`}
          />
          <div className="flex items-center gap-1">
            <label htmlFor={numberId} className="sr-only">{title} 퍼센트 입력</label>
            <input
              id={numberId}
              type="number"
              min={0.1}
              max={100}
              step={0.1}
              value={percent}
              onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
              className="w-16 px-2 py-1 text-sm text-center border border-slate-200 dark:border-slate-700 rounded bg-white dark:bg-slate-800 focus-ring"
              aria-label={`${title} 퍼센트 값`}
            />
            <span className="text-sm text-slate-500" aria-hidden="true">%</span>
          </div>
        </div>
      )}
    </div>
  );
}
