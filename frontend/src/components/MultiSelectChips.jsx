import { useState, useRef, useEffect } from "react";
import { Check, ChevronDown, X } from "lucide-react";

/**
 * Multi-select dropdown with checkboxes.
 * - `options` : [{value, label, extra?}] OR [string]
 * - `values`  : [string] currently selected
 * - `onChange`: (newArray) => void
 * - `placeholder` : shown when nothing selected
 * - `max`     : optional hard cap (defaults 50)
 */
export default function MultiSelectChips({
  options = [],
  values = [],
  onChange,
  placeholder = "Select…",
  max = 50,
  disabled = false,
  testId,
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef(null);

  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const normOpts = options.map((o) => (typeof o === "string" ? { value: o, label: o } : o));
  const filtered = query
    ? normOpts.filter((o) => (o.label + " " + (o.extra || "")).toLowerCase().includes(query.toLowerCase()))
    : normOpts;

  const toggle = (val) => {
    if (disabled) return;
    const has = values.includes(val);
    let next;
    if (has) next = values.filter((v) => v !== val);
    else if (values.length >= max) next = values;
    else next = [...values, val];
    onChange(next);
  };

  const clear = (e) => { e.stopPropagation(); onChange([]); };

  const labelFor = (val) => normOpts.find((o) => o.value === val)?.label || val;

  return (
    <div ref={ref} className="relative" data-testid={testId}>
      <button
        type="button"
        onClick={() => !disabled && setOpen((s) => !s)}
        disabled={disabled}
        className={`w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2 text-left flex items-center gap-2 ${
          disabled ? "opacity-50 cursor-not-allowed" : "hover:border-zinc-600"
        }`}
      >
        <span className="flex-1 flex flex-wrap gap-1 min-h-[20px]">
          {values.length === 0 && <span className="text-zinc-500">{placeholder}</span>}
          {values.slice(0, 4).map((v) => (
            <span key={v} className="bg-blue-900/60 text-blue-200 px-2 py-0.5 rounded text-[11px] flex items-center gap-1">
              {labelFor(v)}
              <X
                className="w-3 h-3 hover:text-white"
                onClick={(e) => { e.stopPropagation(); toggle(v); }}
              />
            </span>
          ))}
          {values.length > 4 && (
            <span className="bg-zinc-700 text-zinc-300 px-2 py-0.5 rounded text-[11px]">
              +{values.length - 4} more
            </span>
          )}
        </span>
        {values.length > 0 && (
          <X className="w-4 h-4 text-zinc-500 hover:text-white" onClick={clear} />
        )}
        <ChevronDown className={`w-4 h-4 text-zinc-400 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <div className="absolute z-50 w-full mt-1 bg-zinc-900 border border-zinc-700 rounded-lg shadow-2xl overflow-hidden">
          <div className="p-2 border-b border-zinc-800">
            <input
              type="text"
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search…"
              className="w-full bg-zinc-950 border border-zinc-700 text-white text-sm rounded px-2 py-1 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div className="max-h-64 overflow-y-auto">
            {filtered.length === 0 && (
              <div className="px-3 py-4 text-sm text-zinc-500 text-center">No matches</div>
            )}
            {filtered.map((o) => {
              const checked = values.includes(o.value);
              return (
                <div
                  key={o.value}
                  onClick={() => toggle(o.value)}
                  className="flex items-center gap-2 px-3 py-1.5 hover:bg-zinc-800 cursor-pointer text-sm"
                >
                  <div
                    className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${
                      checked ? "bg-blue-600 border-blue-600" : "border-zinc-600"
                    }`}
                  >
                    {checked && <Check className="w-3 h-3 text-white" />}
                  </div>
                  <span className="text-zinc-200 flex-1">{o.label}</span>
                  {o.extra && <span className="text-zinc-500 text-xs">{o.extra}</span>}
                </div>
              );
            })}
          </div>
          <div className="flex items-center justify-between px-3 py-1.5 border-t border-zinc-800 bg-zinc-950 text-xs text-zinc-400">
            <span>{values.length} selected</span>
            <div className="flex gap-3">
              <button
                onClick={() => onChange(filtered.slice(0, max).map((o) => o.value))}
                className="hover:text-white"
                type="button"
              >
                Select visible
              </button>
              <button onClick={clear} className="hover:text-white" type="button">
                Clear
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
