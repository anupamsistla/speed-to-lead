import { expect, test } from "@playwright/test";

test("submit a lead and see a booked appointment", async ({ page }) => {
  await page.goto("/");

  // Branding was loaded from the company config, not hardcoded.
  await expect(page.getByRole("heading", { level: 1 })).not.toHaveText("Loading…");
  await expect(page.getByRole("img", { name: /logo/i })).toBeVisible();

  await page.screenshot({ path: "test-results/1-empty.png" });
  await page.getByRole("textbox", { name: "Name" }).fill("Jamie Rivera");
  await page.getByRole("textbox", { name: "Phone" }).fill("+13035550142");
  await page.getByRole("textbox", { name: "Message" }).fill("I own my home in 80205 and want to get started.");
  await page.getByRole("button", { name: "Send lead" }).click();

  // The agent replies and offers times; the first-response timer stops with a number.
  const chat = page.getByRole("log", { name: "Conversation" });
  await expect(chat).toContainText("Which works?");
  await expect(page.getByRole("timer")).toHaveAttribute("data-phase", "done");
  await expect(page.getByRole("timer")).toContainText(/\d+(\.\d)?s/);

  await page.screenshot({ path: "test-results/2-offered.png" });

  // Live trace shows the tool calls that got us here.
  const trace = page.getByRole("list", { name: "Agent Trace" });
  await expect(trace).toContainText("check_existing_contact");
  await expect(trace).toContainText("get_slots");

  // The lead picks a time.
  await page.getByRole("button", { name: "The first one works" }).click();

  const booking = page.getByTestId("booking");
  await expect(booking).toBeVisible();
  await expect(booking).toContainText("Booked");
  await expect(page.getByLabel("Appointment")).toContainText(/consultation/i);
  await expect(page.getByLabel("CRM record")).toContainText("Appointment Booked");
  await expect(page.getByTestId("slack-card")).toHaveCount(2); // hot-lead ping, then booked
  await expect(trace).toContainText("book_appointment");
  await page.screenshot({ path: "test-results/3-booked.png" });
});
