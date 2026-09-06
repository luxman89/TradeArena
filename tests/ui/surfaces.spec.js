import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { entries, fixtures } from "./fixtures.js";

// Model independent visitors so repeated cold-cache journeys do not share an API quota.
test.beforeEach(async ({ context }, info) => {
  await context.setExtraHTTPHeaders({
    "X-Forwarded-For": "ui-" + Date.now() + "-" + info.testId,
  });
});
const sizes = [
  [375, 812],
  [768, 1024],
  [1440, 900],
  [1920, 1080],
];
for (const [width, height] of sizes) {
  test(`primary surfaces at ${width}x${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await fixtures(page);
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    for (const [name, route, ready] of [
      ["leaderboard", "/leaderboard-live", ".ui-ranking"],
      ["profile", "/traders/atlas", ".ui-signal"],
      ["arena", "/arena", ".ui-spectator"],
    ]) {
      await page.goto(route);
      await expect(page.locator(ready).first()).toBeVisible();
      await expect(page.locator(".ui-header")).toHaveCount(1);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBeTruthy();
      if (name === "arena") {
        await expect(page.locator("#arena canvas")).toBeVisible();
        await page.waitForFunction(() => window.arenaRendered === true);
        expect(
          await page.evaluate(() => {
            const arena = document
              .querySelector("#arena")
              .getBoundingClientRect();
            const canvas = document
              .querySelector("#arena canvas")
              .getBoundingClientRect();
            return canvas.top >= arena.top && canvas.bottom <= arena.bottom + 1;
          }),
        ).toBeTruthy();
      }
      await page.evaluate(
        () =>
          new Promise((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(resolve)),
          ),
      );
      await page.screenshot({
        path: `.ui-artifacts/${name}-${width}.png`,
        fullPage: true,
      });
      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(
        results.violations.map((v) => ({
          id: v.id,
          nodes: v.nodes.map((n) => n.target),
        })),
      ).toEqual([]);
      if (name === "arena") {
        const button = page.locator(".ui-spectator").first();
        await button.click();
        await expect(page.getByRole("dialog")).toBeVisible();
        await expect(page.locator("#panel .ui-signal").first()).toBeVisible();
        await page.evaluate(
          () =>
            new Promise((resolve) =>
              requestAnimationFrame(() => requestAnimationFrame(resolve)),
            ),
        );
        await page.screenshot({
          path: `.ui-artifacts/inspector-${width}.png`,
          fullPage: false,
        });
        const dialogResults = await new AxeBuilder({ page })
          .include("#panel")
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze();
        expect(
          dialogResults.violations.map((v) => ({
            id: v.id,
            nodes: v.nodes.map((n) => n.target),
          })),
        ).toEqual([]);
        await page.keyboard.press("Shift+Tab");
        expect(
          await page.evaluate(() =>
            document.querySelector("#panel").contains(document.activeElement),
          ),
        ).toBeTruthy();
        await page.keyboard.press("Escape");
        await expect(page.getByRole("dialog")).not.toBeVisible();
        await expect(button).toBeFocused();
      }
    }
    expect(errors).toEqual([]);
  });
}

test("filters, history, errors, empty and stale data", async ({ page }) => {
  await fixtures(page);
  await page.goto("/leaderboard-live");
  await expect(page.locator(".ui-ranking > li")).toHaveCount(6);
  await page.getByLabel("Division / period").selectOption("crypto");
  await expect(page).toHaveURL(/division=crypto/);
  await expect(page.locator(".ui-ranking > li")).toHaveCount(3);
  await page.goBack();
  await expect(page.locator(".ui-ranking > li")).toHaveCount(6);
  await page.route("**/leaderboard?*", (route) =>
    route.fulfill({ status: 503, body: "" }),
  );
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.locator("#live-status")).toContainText(
    "Updates interrupted",
  );
  await expect(page.locator(".ui-ranking > li")).toHaveCount(6);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Retry rankings" }),
  ).toBeVisible();
  await page.route("**/leaderboard?*", (route) =>
    route.fulfill({ json: { total: 0, entries: [] } }),
  );
  await page.getByRole("button", { name: "Retry rankings" }).click();
  await expect(page.getByText("The next reputation starts here")).toBeVisible();
});

test("loading, safe text, mobile navigation and motion preference", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await fixtures(page);
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  await page.route("**/leaderboard?*", async (route) => {
    await gate;
    await route.fulfill({
      json: {
        total: 1,
        entries: [
          { ...entries[0], display_name: "<img src=x onerror=alert(1)>" },
        ],
      },
    });
  });
  await page.goto("/leaderboard-live");
  await expect(page.getByText("Loading the leaderboard")).toBeVisible();
  await page.screenshot({
    path: ".ui-artifacts/leaderboard-loading-375.png",
    fullPage: true,
  });
  release();
  await expect(page.locator(".ui-ranking a").first()).toHaveText(
    "<img src=x onerror=alert(1)>",
  );
  await expect(page.locator(".ui-ranking img")).toHaveCount(0);
  await page.getByRole("button", { name: "Menu", exact: true }).click();
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Arena", exact: true }).focus();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Menu", exact: true }),
  ).toBeFocused();
  await page.goto("/arena");
  await page.getByText("View controls", { exact: true }).click();
  await page.getByLabel("Motion", { exact: true }).selectOption("off");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-motion", "off");
});

test("landing shell has a no-JavaScript navigation baseline", async ({
  browser,
}) => {
  const context = await browser.newContext({
    javaScriptEnabled: false,
    extraHTTPHeaders: { "X-Forwarded-For": "ui-nojs-" + Date.now() },
    viewport: { width: 375, height: 812 },
  });
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:8765/");
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Leaderboard", exact: true }),
  ).toBeVisible();
  await context.close();
});

test("profile recovery, commitment proof and arena record recovery", async ({
  page,
}) => {
  await fixtures(page);
  await page.route("**/api/v1/users/*/stats", (route) =>
    route.fulfill({ status: 503, body: "" }),
  );
  await page.goto("/traders/atlas");
  await expect(page.getByText("Profile temporarily unavailable")).toBeVisible();
  await page.unroute("**/api/v1/users/*/stats");
  await fixtures(page);
  await page.getByRole("button", { name: "Retry profile" }).click();
  await page
    .getByText("Inspect commitment proof", { exact: true })
    .first()
    .click();
  await expect(
    page.getByText("public-fixture-nonce", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: ".ui-artifacts/profile-proof.png",
    fullPage: true,
  });
  await page.route("**/leaderboard", (route) =>
    route.fulfill({ status: 503, body: "" }),
  );
  await page.goto("/arena");
  await expect(page.getByText("Unable to load competitors")).toBeVisible();
  await page.route("**/leaderboard", (route) =>
    route.fulfill({ json: { total: 0, entries: [] } }),
  );
  await page.getByRole("button", { name: "Refresh record" }).click();
  await expect(page.getByText("The floor is waiting")).toBeVisible();
});

test("landing and component examples at desktop and mobile", async ({
  page,
}) => {
  for (const width of [375, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await expect(page.locator("h1")).toBeVisible();
    await page.screenshot({
      path: `.ui-artifacts/landing-${width}.png`,
      fullPage: true,
    });
    const shell = await new AxeBuilder({ page })
      .include(".ui-header")
      .include(".ui-footer")
      .analyze();
    expect(shell.violations).toEqual([]);
  }
  await page.goto("/ui/examples.html");
  await expect(page.getByText("Evidence before theater.")).toBeVisible();
  await page.getByRole("button", { name: "Retry example" }).click();
  await expect(page.getByRole("status")).toHaveText("Example retry completed.");
});
