import { createContext, useContext, useState, useEffect, useCallback } from "react";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const DEFAULT_BRANDING = {
  app_name: "TrackMaster",
  tagline: "Traffic Tracking & Link Management System",
  logo_url: "",
  favicon_url: "",
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
  login_bg_url: "",
  admin_email: "",
  footer_text: "© 2026 TrackMaster. All rights reserved.",
  sidebar_style: "dark",
  button_style: "rounded",
  font_family: "Inter"
};

const BrandingContext = createContext({
  branding: DEFAULT_BRANDING,
  loading: true,
  refreshBranding: () => {}
});

// Helper to convert hex to HSL for Tailwind CSS variables
function hexToHSL(hex) {
  if (!hex || !hex.startsWith('#')) return null;
  
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
  
  r /= 255;
  g /= 255;
  b /= 255;
  
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h, s, l = (max + min) / 2;

  if (max === min) {
    h = s = 0;
  } else {
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

// Apply branding CSS variables to the document
function applyBrandingStyles(branding) {
  const root = document.documentElement;
  
  // Apply colors as CSS variables (both hex and HSL for flexibility)
  if (branding.primary_color) {
    root.style.setProperty('--brand-primary', branding.primary_color);
    const hsl = hexToHSL(branding.primary_color);
    if (hsl) root.style.setProperty('--primary', hsl);
  }
  
  if (branding.secondary_color) {
    root.style.setProperty('--brand-secondary', branding.secondary_color);
    const hsl = hexToHSL(branding.secondary_color);
    if (hsl) root.style.setProperty('--secondary', hsl);
  }
  
  if (branding.accent_color) {
    root.style.setProperty('--brand-accent', branding.accent_color);
    const hsl = hexToHSL(branding.accent_color);
    if (hsl) root.style.setProperty('--accent', hsl);
  }
  
  if (branding.danger_color) {
    root.style.setProperty('--brand-danger', branding.danger_color);
    const hsl = hexToHSL(branding.danger_color);
    if (hsl) root.style.setProperty('--destructive', hsl);
  }
  
  if (branding.warning_color) {
    root.style.setProperty('--brand-warning', branding.warning_color);
  }
  
  if (branding.success_color) {
    root.style.setProperty('--brand-success', branding.success_color);
  }
  
  if (branding.background_color) {
    root.style.setProperty('--brand-background', branding.background_color);
    const hsl = hexToHSL(branding.background_color);
    if (hsl) root.style.setProperty('--background', hsl);
  }
  
  if (branding.card_color) {
    root.style.setProperty('--brand-card', branding.card_color);
    const hsl = hexToHSL(branding.card_color);
    if (hsl) root.style.setProperty('--card', hsl);
  }
  
  if (branding.border_color) {
    root.style.setProperty('--brand-border', branding.border_color);
    const hsl = hexToHSL(branding.border_color);
    if (hsl) root.style.setProperty('--border', hsl);
  }
  
  if (branding.text_color) {
    root.style.setProperty('--brand-text', branding.text_color);
    const hsl = hexToHSL(branding.text_color);
    if (hsl) {
      root.style.setProperty('--foreground', hsl);
      root.style.setProperty('--card-foreground', hsl);
    }
  }
  
  if (branding.muted_color) {
    root.style.setProperty('--brand-muted', branding.muted_color);
    const hsl = hexToHSL(branding.muted_color);
    if (hsl) root.style.setProperty('--muted-foreground', hsl);
  }
  
  // Apply font family
  if (branding.font_family) {
    root.style.setProperty('--brand-font', branding.font_family);
    root.style.setProperty('font-family', `"${branding.font_family}", system-ui, sans-serif`);
  }
  
  // Apply button style class
  if (branding.button_style) {
    root.setAttribute('data-button-style', branding.button_style);
  }
  
  // Apply sidebar style class
  if (branding.sidebar_style) {
    root.setAttribute('data-sidebar-style', branding.sidebar_style);
  }
}

export function BrandingProvider({ children }) {
  const [branding, setBranding] = useState(DEFAULT_BRANDING);
  const [loading, setLoading] = useState(true);

  const fetchBranding = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/branding`);
      const newBranding = { ...DEFAULT_BRANDING, ...response.data };
      setBranding(newBranding);
      
      // Apply CSS variables
      applyBrandingStyles(newBranding);
      
      // Update document title
      if (response.data.app_name) {
        document.title = response.data.app_name;
      }
      
      // Update favicon if provided
      if (response.data.favicon_url) {
        const link = document.querySelector("link[rel~='icon']") || document.createElement('link');
        link.rel = 'icon';
        link.href = response.data.favicon_url;
        document.head.appendChild(link);
      }
    } catch (error) {
      console.error("Failed to fetch branding:", error);
      // Apply default branding styles on error
      applyBrandingStyles(DEFAULT_BRANDING);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchBranding();
  }, [fetchBranding]);

  const refreshBranding = useCallback(() => {
    fetchBranding();
  }, [fetchBranding]);

  return (
    <BrandingContext.Provider value={{ branding, loading, refreshBranding }}>
      {children}
    </BrandingContext.Provider>
  );
}

export function useBranding() {
  return useContext(BrandingContext);
}

export default BrandingContext;
