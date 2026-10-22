/** Turn one brand hex color into the CSS variables Tailwind's `brand` colors read. */

export type RGB = [number, number, number];

export function hexToRgb(hex: string): RGB {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`not a 6-digit hex color: ${hex}`);
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

/** WCAG relative luminance, 0 (black) to 1 (white). */
export function luminance([r, g, b]: RGB): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

export function contrastRatio(a: RGB, b: RGB): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const WHITE: RGB = [255, 255, 255];
const INK: RGB = [15, 23, 42];

/** Whichever of white or near-black reads better on the given background. */
export function readableOn(bg: RGB): RGB {
  return contrastRatio(bg, WHITE) >= contrastRatio(bg, INK) ? WHITE : INK;
}

export function mix(a: RGB, b: RGB, t: number): RGB {
  return a.map((v, i) => Math.round(v + (b[i] - v) * t)) as RGB;
}

const triplet = (c: RGB) => c.join(" ");

export interface BrandVars {
  "--brand-rgb": string;
  "--brand-fg-rgb": string;
  "--brand-soft-rgb": string;
  "--brand-strong-rgb": string;
}

export function brandVars(hex: string): BrandVars {
  const base = hexToRgb(hex);
  return {
    "--brand-rgb": triplet(base),
    "--brand-fg-rgb": triplet(readableOn(base)),
    "--brand-soft-rgb": triplet(mix(base, WHITE, 0.88)),
    "--brand-strong-rgb": triplet(mix(base, INK, 0.35)),
  };
}

export function applyBrand(hex: string, root: HTMLElement = document.documentElement): void {
  for (const [k, v] of Object.entries(brandVars(hex))) root.style.setProperty(k, v);
}
