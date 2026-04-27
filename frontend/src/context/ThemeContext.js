import { createContext, useContext, useState, useEffect, useCallback } from "react";

const STORAGE_KEY = "realflow-theme";

// ── Theme presets ────────────────────────────────────────────────
// Each preset sets ALL the CSS variables that BrandingContext normally
// controls — so toggling a theme fully swaps the look without
// waiting on server branding.
export const THEMES = {
  dark: {
    name: "Night",
    icon: "moon",
    colors: {
      primary_color: "#3B82F6",
      secondary_color: "#22C55E",
      accent_color: "#8B5CF6",
      danger_color: "#EF4444",
      warning_color: "#F59E0B",
      success_color: "#22C55E",
      background_color: "#09090B",
      card_color: "#18181B",
      border_color: "#27272A",
      text_color: "#FAFAFA",
      muted_color: "#A1A1AA",
    },
  },
  light: {
    name: "Day",
    icon: "sun",
    colors: {
      primary_color: "#2563EB",
      secondary_color: "#16A34A",
      accent_color: "#7C3AED",
      danger_color: "#DC2626",
      warning_color: "#D97706",
      success_color: "#16A34A",
      background_color: "#FFFFFF",
      card_color: "#F4F4F5",
      border_color: "#E4E4E7",
      text_color: "#09090B",
      muted_color: "#52525B",
    },
  },
  // Starting point for custom — user edits these and we persist locally
  custom: {
    name: "Custom",
    icon: "palette",
    colors: {
      primary_color: "#3B82F6",
      secondary_color: "#22C55E",
      accent_color: "#8B5CF6",
      danger_color: "#EF4444",
      warning_color: "#F59E0B",
      success_color: "#22C55E",
      background_color: "#09090B",
      card_color: "#18181B",
      border_color: "#27272A",
      text_color: "#FAFAFA",
      muted_color: "#A1A1AA",
    },
  },
};

// Pre-made color presets for the custom theme picker
export const CUSTOM_PRESETS = [
  {
    name: "Ocean Blue",
    colors: {
      primary_color: "#0EA5E9",
      background_color: "#0C1C2E",
      card_color: "#14283F",
      border_color: "#1E3A5F",
      text_color: "#F0F9FF",
      accent_color: "#06B6D4",
    },
  },
  {
    name: "Forest Green",
    colors: {
      primary_color: "#10B981",
      background_color: "#0A1F1A",
      card_color: "#0F2E26",
      border_color: "#1B3F34",
      text_color: "#F0FDF4",
      accent_color: "#14B8A6",
    },
  },
  {
    name: "Sunset Orange",
    colors: {
      primary_color: "#F97316",
      background_color: "#1F1410",
      card_color: "#2E1F18",
      border_color: "#4A2F22",
      text_color: "#FFF7ED",
      accent_color: "#EAB308",
    },
  },
  {
    name: "Royal Purple",
    colors: {
      primary_color: "#A855F7",
      background_color: "#160F24",
      card_color: "#1F1632",
      border_color: "#322446",
      text_color: "#FAF5FF",
      accent_color: "#EC4899",
    },
  },
  {
    name: "Crimson Red",
    colors: {
      primary_color: "#EF4444",
      background_color: "#1F0D0D",
      card_color: "#2A1616",
      border_color: "#3F2222",
      text_color: "#FEF2F2",
      accent_color: "#F59E0B",
    },
  },
  {
    name: "Pure Light",
    colors: {
      primary_color: "#2563EB",
      background_color: "#FFFFFF",
      card_color: "#F8FAFC",
      border_color: "#E2E8F0",
      text_color: "#0F172A",
      accent_color: "#7C3AED",
    },
  },
];

function hexToHSL(hex) {
  if (!hex || !hex.startsWith("#")) return null;
  let r = 0, g = 0, b = 0;
  if (hex.length === 4) {
    r = parseInt(hex[1] + hex[1], 16);
    g = parseInt(hex[2] + hex[2], 16);
    b = parseInt(hex[3] + hex[3], 16);
  } else if (hex.length === 7) {
    r = parseInt(hex.slice(1, 3), 16);
    g = parseInt(hex.slice(3, 5), 16);
    b = parseInt(hex.slice(5, 7), 16);
  }
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h, s, l = (max + min) / 2;
  if (max === min) { h = s = 0; }
  else {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
      case g: h = ((b - r) / d + 2) / 6; break;
      case b: h = ((r - g) / d + 4) / 6; break;
      default: h = 0;
    }
  }
  return `${Math.round(h * 360)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
}

function applyThemeColors(colors) {
  const root = document.documentElement;
  const map = {
    primary_color: ["--brand-primary", "--primary"],
    secondary_color: ["--brand-secondary", "--secondary"],
    accent_color: ["--brand-accent", "--accent"],
    danger_color: ["--brand-danger", "--destructive"],
    warning_color: ["--brand-warning"],
    success_color: ["--brand-success"],
    background_color: ["--brand-background", "--background", "--card"],
    card_color: ["--brand-card", "--popover"],
    border_color: ["--brand-border", "--border", "--input"],
    text_color: ["--brand-text", "--foreground", "--card-foreground", "--popover-foreground"],
    muted_color: ["--brand-muted", "--muted-foreground"],
  };
  Object.entries(colors || {}).forEach(([key, hex]) => {
    if (!hex) return;
    const targets = map[key] || [];
    const hsl = hexToHSL(hex);
    targets.forEach((cssVar) => {
      if (cssVar.startsWith("--brand-")) {
        root.style.setProperty(cssVar, hex);
      } else if (hsl) {
        root.style.setProperty(cssVar, hsl);
      }
    });
  });
  // Persist light/dark attribute for components that care
  const bg = colors?.background_color || "";
  const isLight = /^#([fF]|[eE])/.test(bg);
  root.setAttribute("data-theme-mode", isLight ? "light" : "dark");
}

const ThemeContext = createContext({
  themeKey: "dark",
  customColors: THEMES.custom.colors,
  setTheme: () => {},
  setCustomColor: () => {},
  applyCustomPreset: () => {},
  resetCustom: () => {},
});

export function ThemeProvider({ children }) {
  const load = () => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return JSON.parse(raw);
    } catch (e) {
      /* ignore */
    }
    return { themeKey: "dark", customColors: THEMES.custom.colors };
  };

  const initial = load();
  const [themeKey, setThemeKey] = useState(initial.themeKey || "dark");
  const [customColors, setCustomColors] = useState(
    initial.customColors || THEMES.custom.colors
  );

  // Apply theme whenever it changes
  useEffect(() => {
    const colors =
      themeKey === "custom" ? customColors : THEMES[themeKey]?.colors;
    if (colors) applyThemeColors(colors);
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ themeKey, customColors })
      );
    } catch (e) {
      /* ignore */
    }
  }, [themeKey, customColors]);

  const setTheme = useCallback((key) => {
    if (THEMES[key]) setThemeKey(key);
  }, []);

  const setCustomColor = useCallback((colorKey, value) => {
    setCustomColors((prev) => ({ ...prev, [colorKey]: value }));
    if (themeKey !== "custom") setThemeKey("custom");
  }, [themeKey]);

  const applyCustomPreset = useCallback((preset) => {
    setCustomColors((prev) => ({ ...prev, ...preset.colors }));
    setThemeKey("custom");
  }, []);

  const resetCustom = useCallback(() => {
    setCustomColors(THEMES.custom.colors);
  }, []);

  return (
    <ThemeContext.Provider
      value={{
        themeKey,
        customColors,
        setTheme,
        setCustomColor,
        applyCustomPreset,
        resetCustom,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}

export default ThemeContext;
