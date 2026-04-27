import { useState } from "react";
import { Moon, Sun, Palette, RotateCcw, Check } from "lucide-react";
import { useTheme, THEMES, CUSTOM_PRESETS } from "../context/ThemeContext";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "./ui/popover";
import { Button } from "./ui/button";

const THEME_BUTTONS = [
  { key: "dark", label: "Night", Icon: Moon },
  { key: "light", label: "Day", Icon: Sun },
  { key: "custom", label: "Custom", Icon: Palette },
];

const CUSTOM_FIELDS = [
  { key: "primary_color", label: "Primary" },
  { key: "accent_color", label: "Accent" },
  { key: "background_color", label: "Background" },
  { key: "card_color", label: "Card" },
  { key: "text_color", label: "Text" },
  { key: "border_color", label: "Border" },
];

export default function ThemeToggle() {
  const {
    themeKey,
    customColors,
    setTheme,
    setCustomColor,
    applyCustomPreset,
    resetCustom,
  } = useTheme();
  const [open, setOpen] = useState(false);

  const ActiveIcon =
    THEME_BUTTONS.find((t) => t.key === themeKey)?.Icon || Moon;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          data-testid="theme-toggle-btn"
          aria-label="Change theme"
          className="h-9 w-9 rounded-full hover:bg-[var(--brand-card)] text-[var(--brand-text)]"
        >
          <ActiveIcon className="h-5 w-5" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        className="w-[320px] p-0 border-[var(--brand-border)] bg-[var(--brand-card)]"
        data-testid="theme-popover"
      >
        {/* ── Mode selector ───────────────────────────────────── */}
        <div className="p-4 border-b border-[var(--brand-border)]">
          <div className="text-xs uppercase tracking-wider text-[var(--brand-muted)] mb-2">
            Theme
          </div>
          <div className="grid grid-cols-3 gap-2">
            {THEME_BUTTONS.map(({ key, label, Icon }) => {
              const active = themeKey === key;
              return (
                <button
                  key={key}
                  onClick={() => setTheme(key)}
                  data-testid={`theme-mode-${key}`}
                  className={`flex flex-col items-center justify-center gap-1.5 py-3 rounded-lg border transition-all
                    ${active
                      ? "border-[var(--brand-primary)] bg-[var(--brand-primary)]/15 text-[var(--brand-text)]"
                      : "border-[var(--brand-border)] bg-transparent text-[var(--brand-muted)] hover:text-[var(--brand-text)] hover:border-[var(--brand-primary)]/50"
                    }`}
                >
                  <Icon className="h-4 w-4" />
                  <span className="text-xs font-medium">{label}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* ── Custom theme controls ─────────────────────────── */}
        {themeKey === "custom" && (
          <div className="p-4 max-h-[420px] overflow-y-auto">
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs uppercase tracking-wider text-[var(--brand-muted)]">
                Presets
              </div>
              <button
                onClick={resetCustom}
                className="flex items-center gap-1 text-xs text-[var(--brand-muted)] hover:text-[var(--brand-text)] transition-colors"
                data-testid="theme-reset-custom"
              >
                <RotateCcw className="h-3 w-3" /> Reset
              </button>
            </div>
            <div className="grid grid-cols-3 gap-2 mb-4">
              {CUSTOM_PRESETS.map((p) => (
                <button
                  key={p.name}
                  onClick={() => applyCustomPreset(p)}
                  data-testid={`theme-preset-${p.name.toLowerCase().replace(/\s+/g, "-")}`}
                  className="group relative h-12 rounded-lg border border-[var(--brand-border)] overflow-hidden hover:border-[var(--brand-primary)] transition-all"
                  style={{ background: p.colors.background_color }}
                >
                  <div className="absolute inset-x-0 bottom-0 h-6 flex">
                    <div className="flex-1" style={{ background: p.colors.primary_color }} />
                    <div className="flex-1" style={{ background: p.colors.accent_color }} />
                    <div className="flex-1" style={{ background: p.colors.card_color }} />
                  </div>
                  <div className="absolute inset-0 flex items-end justify-center pb-0.5">
                    <span
                      className="text-[9px] font-semibold uppercase tracking-wide"
                      style={{ color: p.colors.text_color }}
                    >
                      {p.name}
                    </span>
                  </div>
                </button>
              ))}
            </div>

            <div className="text-xs uppercase tracking-wider text-[var(--brand-muted)] mb-2">
              Custom Colors
            </div>
            <div className="space-y-2">
              {CUSTOM_FIELDS.map(({ key, label }) => (
                <label
                  key={key}
                  className="flex items-center gap-3 py-1.5 cursor-pointer"
                  data-testid={`theme-color-${key}`}
                >
                  <input
                    type="color"
                    value={customColors[key] || "#000000"}
                    onChange={(e) => setCustomColor(key, e.target.value)}
                    className="h-8 w-8 rounded-md border border-[var(--brand-border)] bg-transparent cursor-pointer"
                    data-testid={`theme-color-input-${key}`}
                  />
                  <div className="flex-1">
                    <div className="text-sm text-[var(--brand-text)]">{label}</div>
                    <div className="text-xs text-[var(--brand-muted)] font-mono uppercase">
                      {customColors[key]}
                    </div>
                  </div>
                  <Check className="h-4 w-4 text-[var(--brand-primary)] opacity-60" />
                </label>
              ))}
            </div>
          </div>
        )}

        {/* ── Info footer for preset themes ─────────────────── */}
        {themeKey !== "custom" && (
          <div className="p-4 text-xs text-[var(--brand-muted)]">
            <span className="text-[var(--brand-text)] font-medium">
              {THEMES[themeKey]?.name} mode
            </span>{" "}
            active. Switch to <strong>Custom</strong> to pick your own colors.
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
