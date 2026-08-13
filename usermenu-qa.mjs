export default async function run(page, ui) {
  const report = { steps: [] };

  // 1. Should land on login page.
  let snap = await ui.snapshot();
  report.initialSnapshot = snap;

  const signupLinkMatch = snap.match(/@(e\d+) link "[^"]*Sign ?up[^"]*"/i) || snap.match(/@(e\d+) button "[^"]*Sign ?up[^"]*"/i);
  if (signupLinkMatch) {
    await ui.click(`@${signupLinkMatch[1]}`);
    await page.waitForTimeout(400);
  } else {
    await page.goto("http://localhost:5173/signup");
    await page.waitForTimeout(400);
  }

  snap = await ui.snapshot({ full: true });
  report.signupPageSnapshot = snap;

  // Fill signup form using accessible labels via getByLabel/getByPlaceholder fallback.
  async function fillFirst(locatorCandidates, value) {
    for (const loc of locatorCandidates) {
      try {
        const count = await loc.count();
        if (count > 0) {
          await loc.first().fill(value);
          return true;
        }
      } catch (e) {
        // try next
      }
    }
    return false;
  }

  const emailOk = await fillFirst(
    [page.getByLabel(/email/i), page.locator('input[type="email"]'), page.locator('input[name="email"]')],
    "usermenu-test@example.com"
  );
  const passOk = await fillFirst(
    [page.getByLabel(/^password$/i), page.locator('input[type="password"]').first()],
    "TestPass123!"
  );
  const nameOk = await fillFirst(
    [page.getByLabel(/full name/i), page.locator('input[name="full_name"]'), page.locator('input[name="fullName"]')],
    "Ada Lovelace"
  );
  const orgOk = await fillFirst(
    [page.getByLabel(/organization/i), page.locator('input[name="organization_name"]'), page.locator('input[name="organizationName"]')],
    "Acme Test Co"
  );

  report.fillResults = { emailOk, passOk, nameOk, orgOk };

  snap = await ui.snapshot();
  report.beforeSubmitSnapshot = snap;

  const submitMatch = snap.match(/@(e\d+) button "[^"]*Sign ?up[^"]*"/i) || snap.match(/@(e\d+) button "[^"]*Create[^"]*"/i);
  if (submitMatch) {
    await ui.click(`@${submitMatch[1]}`);
  } else {
    await page.keyboard.press("Enter");
  }

  await page.waitForTimeout(1200);

  snap = await ui.snapshot({ full: true });
  report.afterSignupSnapshot = snap;
  report.urlAfterSignup = page.url();

  // 2. Look for account control in header.
  const accountMatch = snap.match(/@(e\d+) button "Account menu"/);
  report.accountControlFound = !!accountMatch;

  if (accountMatch) {
    await ui.click(`@${accountMatch[1]}`);
    await page.waitForTimeout(300);
    const openSnap = await ui.snapshot({ full: true });
    report.openMenuSnapshot = openSnap;
    report.emailVisibleInMenu = openSnap.includes("usermenu-test@example.com");
    report.logoutVisible = /Log ?out/i.test(openSnap);

    await page.screenshot({ path: "C:\\Users\\TANVI~1.TAK\\AppData\\Local\\Temp\\claude\\C--Users-tanvi-takle-Data-Recon\\89483ad4-9c30-4746-97f4-b6076aade136\\scratchpad\\usermenu-open.png" });

    // 3. Click outside to close.
    await page.mouse.click(10, 300);
    await page.waitForTimeout(300);
    const closedSnap = await ui.snapshot();
    report.closedAfterOutsideClick = !closedSnap.includes("Log out");

    // Reopen and click logout.
    const reSnap = await ui.snapshot();
    const accountMatch2 = reSnap.match(/@(e\d+) button "Account menu"/);
    if (accountMatch2) {
      await ui.click(`@${accountMatch2[1]}`);
      await page.waitForTimeout(300);
      const openSnap2 = await ui.snapshot();
      const logoutMatch = openSnap2.match(/@(e\d+) button "[^"]*Log ?out[^"]*"/i);
      if (logoutMatch) {
        await ui.click(`@${logoutMatch[1]}`);
        await page.waitForTimeout(800);
        report.urlAfterLogout = page.url();
        const afterLogoutSnap = await ui.snapshot({ full: true });
        report.afterLogoutSnapshot = afterLogoutSnap;
      }
    }
  }

  // 4. Log back in.
  await page.goto("http://localhost:5173/login");
  await page.waitForTimeout(500);
  const loginEmailOk = await fillFirst(
    [page.getByLabel(/email/i), page.locator('input[type="email"]'), page.locator('input[name="email"]')],
    "usermenu-test@example.com"
  );
  const loginPassOk = await fillFirst(
    [page.getByLabel(/^password$/i), page.locator('input[type="password"]').first()],
    "TestPass123!"
  );
  report.reLoginFillResults = { loginEmailOk, loginPassOk };

  const loginSnap = await ui.snapshot();
  const loginBtnMatch = loginSnap.match(/@(e\d+) button "[^"]*(Sign ?in|Log ?in)[^"]*"/i);
  if (loginBtnMatch) {
    await ui.click(`@${loginBtnMatch[1]}`);
  } else {
    await page.keyboard.press("Enter");
  }
  await page.waitForTimeout(1000);
  report.urlAfterRelogin = page.url();

  // 5. Refresh and check session persists.
  await page.reload();
  await page.waitForTimeout(1000);
  const afterReloadSnap = await ui.snapshot({ full: true });
  report.urlAfterReload = page.url();
  report.accountControlPersistsAfterReload = /Account menu/.test(afterReloadSnap);

  return report;
}
