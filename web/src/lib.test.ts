import { humanize } from "./lib";

describe("humanize", () => {
  it("keeps the dash in numeric ranges", () => {
    expect(humanize("1_3_months")).toBe("1-3 months");
    expect(humanize("3_12_months")).toBe("3-12 months");
  });

  it("writes 740_plus as 740+", () => {
    expect(humanize("740_plus")).toBe("740+");
  });

  it("still turns other underscores into spaces", () => {
    expect(humanize("heavy_fabrications")).toBe("Heavy fabrications");
  });
});
