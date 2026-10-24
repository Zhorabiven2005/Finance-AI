import { Input } from "@/components/ui/Field";
import { cn } from "@/lib/cn";
import { PERIOD_PRESET_LABEL, type PeriodPreset } from "@/lib/period";

export function PeriodPicker({
  preset,
  onPresetChange,
  customFrom,
  customTo,
  onCustomChange,
  presets,
}: {
  preset: PeriodPreset;
  onPresetChange: (preset: PeriodPreset) => void;
  customFrom: string;
  customTo: string;
  onCustomChange: (from: string, to: string) => void;
  presets: PeriodPreset[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {presets.map((p) => (
        <button
          key={p}
          type="button"
          onClick={() => onPresetChange(p)}
          className={cn(
            "rounded-lg px-3.5 py-2 text-sm font-medium transition-colors",
            preset === p
              ? "bg-accent-soft text-accent"
              : "text-ink-500 hover:bg-surface-hover hover:text-ink-900",
          )}
        >
          {PERIOD_PRESET_LABEL[p]}
        </button>
      ))}
      {preset === "custom" && (
        <div className="flex items-center gap-2">
          <Input
            type="date"
            value={customFrom}
            onChange={(e) => onCustomChange(e.target.value, customTo)}
            className="h-10 w-auto"
          />
          <span className="text-ink-400">—</span>
          <Input
            type="date"
            value={customTo}
            onChange={(e) => onCustomChange(customFrom, e.target.value)}
            className="h-10 w-auto"
          />
        </div>
      )}
    </div>
  );
}
