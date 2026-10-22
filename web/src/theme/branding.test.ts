import { applyBrand, brandVars, contrastRatio, hexToRgb, readableOn } from "./branding";

describe("branding", () => {
  it("parses hex colors", () => {
    expect(hexToRgb("#F59E0B")).toEqual([245, 158, 11]);
    expect(hexToRgb("1d4ed8")).toEqual([29, 78, 216]);
    expect(() => hexToRgb("orange")).toThrow();
  });

  it("picks readable text for light and dark brand colors", () => {
    expect(readableOn(hexToRgb("#F59E0B"))).toEqual([15, 23, 42]); // amber gets dark text
    expect(readableOn(hexToRgb("#0F2A4A"))).toEqual([255, 255, 255]); // navy gets white
  });

  it.each(["#F59E0B", "#0F2A4A", "#16A34A", "#DC2626", "#FACC15", "#7C3AED"])(
    "text on %s meets WCAG AA contrast",
    (hex) => {
      const bg = hexToRgb(hex);
      expect(contrastRatio(bg, readableOn(bg))).toBeGreaterThanOrEqual(4.5);
    },
  );

  it("derives soft and strong shades from one color", () => {
    const v = brandVars("#1D4ED8");
    expect(v["--brand-rgb"]).toBe("29 78 216");
    const soft = v["--brand-soft-rgb"].split(" ").map(Number);
    const strong = v["--brand-strong-rgb"].split(" ").map(Number);
    expect(Math.min(...soft)).toBeGreaterThan(200); // a pale tint
    expect(Math.max(...strong)).toBeLessThan(216); // darker than the base
  });

  it("applies CSS variables to the document so Tailwind brand colors change", () => {
    const el = document.createElement("div");
    applyBrand("#16A34A", el);
    expect(el.style.getPropertyValue("--brand-rgb")).toBe("22 163 74");
    applyBrand("#DC2626", el);
    expect(el.style.getPropertyValue("--brand-rgb")).toBe("220 38 38");
  });
});
