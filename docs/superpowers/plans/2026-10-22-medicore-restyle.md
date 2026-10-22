# Medicore restyle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt the Figma "Medicore" look across the app shell, workspace, dashboard and every module screen via a token remap + shell rebuild, with zero behaviour loss.

**Architecture:** One CSS token layer flip (theme.css/globals.css) reskins every screen that already consumes shadcn semantic tokens; the chrome components (AppHeader/AppSidebar) are restyled in place to theme-scoped tokens; a shared PageHeading unifies page headers; the dashboard is rebuilt on the mock's "Modern" layout with CSS-only charts. Backend and dependencies untouched.

**Tech Stack:** React 18.3, TypeScript 5.9 (strict), Tailwind CSS v4 (`@theme inline`, `@custom-variant dark`), shadcn/ui vendored components, Vitest + Testing Library, React Router 7, TanStack Query 5, Zustand (themeStore — untouched).

**Spec:** `docs/superpowers/specs/2026-10-22-medicore-restyle-design.md` (incl. §4 builder-check resolutions — the plan argues from it; executors read both).

## Global Constraints

- No new npm dependencies; fonts extend the existing `index.html` Google Fonts `<link>` (Inter + Noto Sans Devanagari stay; add DM Sans 500/600/700 + DM Mono 400/500; JetBrains Mono retires).
- No backend change; `python -m ruff check . ../tests` and `python -m pytest` must still pass at the end (drift proof only).
- Do NOT commit the user's own edits: `frontend/vite.config.ts` (`host: '0.0.0.0'`) and `backend/apps/patient_registry/migrations/0012_*.py`. Each task commits only the files it lists.
- No hardcoded palette colours in components/theme-scoped classes — every colour goes through a token (shadcn theming rule; AGENTS §5).
- Chrome tokens (`--shell-*`) become theme-scoped; the two CI guards that forbid this are deliberately inverted (spec §4.2), never deleted.
- Text that carries information never uses the faint tier (≈2.4–3.7:1); it sits on the soft/strong token tier (spec §4.3).
- No `AllowAny`-style shortcuts apply here; no fake data presented as real, no dead controls, no dead links (AGENTS §5, spec §4.7, §4.12).
- Components: functional-only, hooks, effect cleanup, `@/` alias imports, 2-space TS style with semicolons and double quotes.

## Review Focus

- White-on-white chrome: any leftover `text-white`/`bg-white/10`-style utility on the restyled light topbar → invisible control. Pinned by AppHeader/AppSidebar updated coverage (Task 3/4: iterate every footer/heading/topbar control and assert by role/name; the CI contrast test pins the token pairs themselves).
- Light-mode rail regression (the ORIGINAL bug): rail foregrounds becoming theme-scoped the wrong way. Pinned by the inverted guards in `styles.unit.test.ts` + `AppShell.integration.test.tsx` (Task 1/3).
- Disabled-state integrity: chips must not introduce colour-only state; disabled entries keep aria-disabled + title + release tag (Task 3) and the dashboard strip renders them disabled, not as dead links (Task 7).
- Heading hierarchy: exactly one h1 per route after the sweep; PatientDetail keeps UHID info as h2 (Task 6 step asserts by level).
- Theme system preference: the Light/Dark switcher must not silently destroy the `system` preference contract — three segments pinned by test (Task 3).

---

### Task 1: Medicore tokens + web fonts + README note

**Files:**
- Modify: `frontend/src/styles/theme.css` (all values; structure comment rewritten)
- Modify: `frontend/src/styles/globals.css` (token remap, brand-accent registration, font tokens)
- Modify: `frontend/index.html` (font `<link>`)
- Modify: `frontend/src/styles/styles.unit.test.ts` (inverted guards + new pairs)
- Modify: `README.md` (Tech stack: font line)

**Interfaces:**
- Produces (consumed by every later task): chrome tokens `--shell-sidebar/--shell-topbar/--shell-sidebar-foreground/--shell-sidebar-subtle/--shell-sidebar-hover/--shell-sidebar-border/--shell-active/--shell-active-foreground`; brand tokens registered in `@theme inline` as `--color-brand-accent/-strong/-soft/-ink` (+ `-soft-strong` NOT needed); re-pointed `--canvas-dashboard/--surface/--surface-subtle/--text-primary/--text-secondary`, `--tone-positive`, `--chart-fill-1/-2`, shadcn `--primary/--primary-foreground/--ring/--border/--input/--background/--card/--muted...`, `--sidebar-*` aligned to chrome; font utilities `font-display` (`DM Sans`), `font-mono` (`DM Mono`).

- [ ] **Step 1: Write the failing tests (rewrite `styles.unit.test.ts` pairs)**

Keep the file's existing helpers (hex `token()`; extend `token()` to accept `rgb(a)` strings: change the match regex to `[#()]` form `((?:#[0-9a-fA-F]{3,8})|(?:rgba?\([^)]+\)))` — CQ-15). New assertions (exact pairs, both supplies):

```ts
// light
expect(contrast(token("--shell-sidebar-foreground"), token("--shell-sidebar"))).toBeGreaterThanOrEqual(4.5);
expect(contrast(token("--shell-sidebar-subtle"), token("--shell-sidebar"))).toBeGreaterThanOrEqual(4.5);
expect(contrast(token("--shell-active-foreground"), token("--shell-active"))).toBeGreaterThanOrEqual(4.5);
expect(contrast(token("--shell-topbar-foreground"), token("--shell-topbar"))).toBeGreaterThanOrEqual(4.5);
expect(contrast(token("--primary-foreground"), token("--primary"))).toBeGreaterThanOrEqual(4.5);
expect(contrast(token("--brand-accent-ink"), WHITE)).toBeGreaterThanOrEqual(4.5);
// dark — .dark block supplies hex shell values; helper slices the block
expect(contrast(darkHex("--shell-sidebar-foreground"), darkHex("--shell-sidebar"))).toBeGreaterThanOrEqual(4.5);
expect(contrast(darkHex("--shell-topbar-foreground"), darkHex("--shell-topbar"))).toBeGreaterThanOrEqual(4.5);
expect(contrast(darkHex("--primary-foreground"), darkHex("--primary"))).toBeGreaterThanOrEqual(4.5);
// boundary
expect(contrast(token("--shell-sidebar-hover"), token("--shell-sidebar"))).toBeGreaterThan(1.05);
// inverted theme-independence guard: chrome tokens now exist in BOTH blocks
for (const name of ["--shell-sidebar-foreground", "--shell-sidebar-subtle", "--shell-topbar-foreground"]) {
  expect(darkBlock).toContain(name);   // was: darkBlock NOT contain
}
expect(darkBlock).toContain("--canvas-dashboard:");
expect(darkBlock).toContain("--surface:"); ... (keep existing canvas/surface assertions)
```

`darkHex` = helper reading the `.dark` block only (hex or rgba; for rgba `--brand-accent-soft` do not assert contrast — decorative soft fill).

- [ ] **Step 2: Run — expect FAIL** — `npm run test -- src/styles/styles.unit.test.ts` → current theme.css lacks the new values.
- [ ] **Step 3: Apply the token values**

`theme.css` — section 1 becomes theme-scoped (tokens declared in `:root` AND `.dark`). Exact values:

```
:root (light chrome):
  --shell-sidebar:#FBFDFD;  --shell-topbar:#FFFFFF;
  --shell-sidebar-foreground:#17212B;  --shell-sidebar-subtle:#617078;
  --shell-sidebar-hover:#EEF4F6;  --shell-sidebar-border:#E2EBEC;
  --shell-active:#DFF8EF;  --shell-active-foreground:#073C2F;
.dark (dark chrome):
  --shell-sidebar:#1C2940;  --shell-topbar:#283A56;
  --shell-sidebar-foreground:#F4F7FA;  --shell-sidebar-subtle:#AEBBC9;
  --shell-sidebar-hover:#24334C;  --shell-sidebar-border:#334761;
  --shell-active:#1B3C49;  --shell-active-foreground:#F4F7FA;
```

(These must pass the pairs above; they do — e.g. `#617078` on `#FBFDFD` ≈ 4.7:1, `#073C2F` on `#DFF8EF` ≈ 10:1, hover boundary ≈1.06.)

Dashboard surfaces section: light `--canvas-dashboard` = `#dbe5e8` as triplet `197 29% 89%`, `--surface` stays white, `--surface-subtle` = `180 27% 96%` (#F4F8F8), `--text-primary` = `210 28% 13%` (#17212B), `--text-secondary` = `200 11% 42%` (#617078); `.dark`: canvas `196 13% 82%` (#CBD7DA), surface `218 23% 25%` (#2A3A55), surface-subtle `218 35% 22%` (#24334C), text-primary `210 30% 97%`, text-secondary `211 18% 74%`. Tones: light `--tone-positive` = `160 90% 25%` (#067a54); dark `--tone-positive` = `158 63% 51%` (#28D79D). Charts: `--chart-fill-1` light `160 77% 43%` (#18C58D), `--chart-fill-2` light `160 45% 71%` (42% tint); dark fill-1 `160 62% 51%`, fill-2 `160 45% 66%`. Keep fill-3/-4/-5.

`globals.css` — in the `:root`/`.dark` base layer, set: `--primary` light `160 77% 43%` (#18C58D) / dark same; `--primary-foreground` light `166 85% 13%` (#073C2F) / dark `166 85% 13%`; `--ring` light = primary triplet, dark `158 63% 51%`; `--background` light `197 29% 89%` (canvas) / dark `196 13% 82%`; `--foreground` = text-primary values; `--card` = surface values, `--card-foreground` = foreground; `--muted` = surface-subtle values; `--muted-foreground` = text-secondary values; `--border`/`--input` light `189 27% 91%` (#E2EBEC) / dark `218 30% 29%` (#334761). Align `--sidebar-*` to the chrome pairs. Add brand tokens (both blocks):

```
:root: --brand-accent:#18C58D; --brand-accent-strong:#0EAC77;
       --brand-accent-soft:#DFF8EF; --brand-accent-ink:#067A54;
.dark: --brand-accent:#18C58D; --brand-accent-strong:#28D79D;
       --brand-accent-soft:rgba(24,197,141,0.12); --brand-accent-ink:#28D79D;
```

Get alpha composition: tokens here may be hex/rgba consumed bare (follow the existing `--color-chart-fill-5: var(--chart-fill-5)` precedent — unwrapped reference in `@theme inline`); register in `@theme`: `--font-display: "DM Sans", system-ui, sans-serif;` and change `--font-mono` default to `"DM Mono", monospace` (Tailwind v4 `--font-*` theme namespace generates `font-display`/`font-mono` utilities). Remove the repo's JetBrains Mono references (grep `JetBrains` — index.html link + any font-mono fallback lists).

- [ ] **Step 4: index.html `<link>`** — one `fonts.googleapis.com/css2?...` URL = Inter (unchanged) `&family=DM+Sans:wght@500;600;700&family=DM+Mono:wght@400;500`.
- [ ] **Step 5: Run styles test** — expect PASS: `npm run test -- src/styles/styles.unit.test.ts`.
- [ ] **Step 6: README** — `## Tech stack` frontend paragraph: add `Fonts: Inter (body), DM Sans (display), DM Mono (codes) via a single Google Fonts stylesheet link (runtime asset, not an npm dependency).`
- [ ] **Step 7: Commit**

```bash
git add frontend/src/styles/theme.css frontend/src/styles/globals.css frontend/index.html frontend/src/styles/styles.unit.test.ts README.md
git commit -m "feat(ui): adopt Medicore theme tokens + web fonts"
```

### Task 2: Nav codes

**Files:**
- Modify: `frontend/src/lib/navigation.ts`
- Test: `frontend/src/lib/navigation.unit.test.ts`

**Interfaces:**
- Produces: `NavItem.code: string` — two uppercase letters, unique across all 36 items (AGENTS: DB/PR对了→ codes: dashboard DB, patients PR, opd OP, ipd IP, emr EM, emergency ER, icu IC, ot OT, lis LB, ris RD, pharmacy RX, blood-bank BB, insurance IN, billing BI, tariffs TF, claims CL, quality-os QO, capa CA, data-quality DQ, alerts AL, assessments AS, reports RE, users UR, departments DE, wards-beds WB, facility-setup FS, config-history CH, registration-config RC, quality-profile QP, abdm-qr AQ, audit AU, notifications NO, abdm-exchange AB, integrations IG, tenants PT). Group `settings.label` renamed `"Configuration & setups"`.

- [ ] **Step 1: Failing test** in navigation.unit.test.ts:

```ts
it("gives every nav item a unique two-letter code", () => {
  const codes = NAV_ITEMS.map((i) => i.code);
  expect(codes).toHaveLength(new Set(codes).size);
  for (const code of codes) expect(code).toMatch(/^[A-Z]{2}$/);
});
```
Plus update the group-label expectations (`["Main Menu", "Configuration & setups"]`).

- [ ] **Step 2: Run** `npm run test -- src/lib/navigation.unit.test.ts` → FAIL (no `code`).
- [ ] **Step 3: Implement** — add `code: string` to the `NavItem` interface + `item()` signature; annotate the module docstring that codes mirror the Medicore nav-chip design (spec §2.3).
- [ ] **Step 4: Run — expect PASS** (all nav tests).
- [ ] **Step 5: Commit** `git add src/lib/navigation.ts src/lib/navigation.unit.test.ts && git commit -m "feat(nav): add two-letter nav codes"`.

### Task 3: AppSidebar — brand block, chips, footer switcher

**Files:**
- Modify: `frontend/src/components/AppSidebar.tsx`
- Test: `frontend/src/components/AppShell.integration.test.tsx` (sidebar describe)

**Interfaces:**
- Consumes: `NavItem.code` (Task 2), themeStore `setPreference/resolved/preference` (existing).
- Produces: sidebar footer segment `Light | Dark | System` (three `<button aria-pressed>` driven by `preference`), version line `Mediflow OS · React 18 · Django 5.2`; brand block (`M` mark = `bg-primary text-primary-foreground`, wordmark `MEDIFLOW`, sub `HOSPITAL INFORMATION SYSTEM`).

- [ ] **Step 1: Test updates (write first):**

```ts
it("renders nav-code chips for every entry", () => { // DB beside Dashboard
  renderWithProviders(<AppSidebar />);
  const db = screen.getByText("DB");
  expect(db).toHaveTextContent("DB");
  // chip precedes the label in link markup — position via closest link
  expect(db.closest("a") ?? db.closest("[aria-disabled]")).not.toBeNull();
});
it("renames the second group", ... getByRole heading name "Configuration & setups" ...);
it("offers Light/Dark/System in the footer switcher", () => {
  renderWithProviders(<AppSidebar />);
  for (const label of ["Light", "Dark", "System"]) {
    const b = screen.getByRole("button", { name: label });
    expect(b).toHaveAttribute("aria-pressed", String(useThemeStore.getState().preference === label.toLowerCase()));
  }
});
it("switching to Dark persists an explicit preference", () => {
  renderWithProviders(<AppSidebar />);
  fireEvent.click(screen.getByRole("button", { name: "Dark" }));
  expect(useThemeStore.getState().preference).toBe("dark");
  expect(document.documentElement.classList.contains("dark")).toBe(true);
});
```
(Update, keep: brand "MEDIFLOW" text; removed: "Main Menu"/"Settings" old names; header ThemeToggle assertions move out in Task 4; the old `theme independence` component guard becomes: rail html still contains `bg-shell-sidebar` + `text-shell-sidebar-` classes (harmless), drop the `text-sidebar-foreground`-negative assertions — replaced by Task 1 CI-level guard. Collapsed test now ALSO asserts code chip remains visible: `screen.getByText("DB")` still shown while label hidden (existing sr-only behaviour unchanged).)
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Restyle component** — structure:

```tsx
<aside …bg-shell-sidebar text-shell-sidebar-foreground border-shell-sidebar-border>
  <div brand: size-8 rounded-[10px] bg-primary text-primary-foreground grid place-items-center font-display font-bold>M</div>
    <div><strong className="font-display text-xs tracking-[0.08em]">MEDIFLOW</strong>
         <span className="text-[10px] uppercase tracking-[0.08em] text-shell-sidebar-subtle">Hospital Information System</span></div>
  <nav aria-label="Primary">
    groups as today; Group h2 keeps role=heading semantics (name now "Configuration & setups")
    entry row: <span className="…size-[26px] rounded-md border border-shell-sidebar-border font-mono text-[10px] grid place-items-center">{entry.code}</span>
               <span className="truncate text-sm">{label}</span>
               disabled: keep release tag right + title
    active (NavLink isActive): "bg-shell-active font-semibold text-shell-active-foreground"; hover: "hover:bg-shell-sidebar-hover"
    focus ring: "focus-visible:ring-2 focus-visible:ring-shell-sidebar-subtle" (replaces ring-white)
  </nav>
  <div className="sidebar-footer border-t border-shell-sidebar-border">
    <div role="group" aria-label="Theme selection" className="grid grid-cols-3 rounded-lg border border-shell-sidebar-border bg-shell-sidebar-hover p-0.5">
      {(["light","dark","system"] as const).map(p => <button key={p} aria-pressed={preference===p}
          className={preference===p ? "bg-shell-topbar text-shell-sidebar-foreground rounded-md shadow-sm" : "text-shell-sidebar-subtle"}
          onClick={() => setPreference(p)}>{label}</button>)}
    </div>
    <p className="font-mono text-[10px] text-shell-sidebar-subtle">Mediflow OS · React 18 · Django 5.2</p>
  </div>
</aside>
```
Drawer: same chip style (kept structurally). Collapsed rail: chip visible, label sr-only (unchanged pattern), footer hidden when collapsed (`collapsed && "hidden"`).
- [ ] **Step 4: Run** → PASS. Commit: `git add components/AppSidebar.tsx components/AppShell.integration.test.tsx && git commit -m "feat(ui): restyle sidebar with nav-code chips + theme switcher"`.

### Task 4: AppHeader — light chrome + real status chip

**Files:**
- Modify: `frontend/src/components/AppHeader.tsx`
- Delete: `frontend/src/components/ThemeToggle.tsx` (verify no other importer first: only AppHeader imports it)
- Test: `frontend/src/components/AppShell.integration.test.tsx` (header describe)

**Interfaces:**
- Consumes: `fetchHealth` (`@/lib/health`, existing; query shape `["health"]` with `retry:false, refetchInterval:30_000` — mirrors spec + existing dashboard query).
- Produces: topbar status chip `role="status"`: `status === "ok"` → dot + "Operational" (`text-tone-positive`, dot `bg-tone-positive`), otherwise amber "API unreachable" word. Login/Demo badge unchanged.

- [ ] **Step 1: Test updates:**

```ts
it("keeps the real connection state visible, not colour alone", () => { // stub 200 /health/
  vi.stubGlobal("fetch", okUrlJson("/health/", { status: "ok" }));
  renderWithProviders(<AppHeader />);
  expect(await screen.findByText("Operational")).toBeInTheDocument();
});
it("names the unreachable state", () => { // stub 500
  vi.stubGlobal("fetch", failUrl("/health/"));
  renderWithProviders(<AppHeader />);
  expect(await screen.findByText(/API unreachable/i)).toBeInTheDocument();
});
```
Archive the two ThemeToggle tests (delete `Theme:` button tests); keep the rest of the header assertions (Mediflow OS, Tenant/Facility labels, search field, Ctrl K, icon-only names, demo/live badge).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Restyle** — container: `sticky top-0 z-40 flex h-16 items-center gap-3 bg-shell-topbar text-foreground border-b border-shell-sidebar-border px-4 md:px-6`. Replace every legacy white utility: menu/collapse/bell buttons `text-foreground hover:bg-foreground/5 focus-visible:ring-shell-sidebar-subtle`; selects `border-shell-sidebar-border bg-shell-sidebar-hover text-foreground` (foreground `<option>` stays); logo tile unchanged (`bg-primary text-primary-foreground`); search Input `border-border bg-surface-subtle pl-8 pr-14 text-foreground placeholder:text-muted-foreground focus-visible:ring-ring`, Search icon `text-muted-foreground`; kbd `border-border bg-shell-sidebar-hover text-muted-foreground`; sign-out block unchanged (DropdownMenu already token-driven). **Live/Demo badge**: `bg-green-600` light variant → `bg-tone-positive text-background` (word "Live Data" already carries meaning; tone tokens are the CI-mindful pairs), demo variant `border-border bg-shell-sidebar-hover text-text-secondary`. Status chip: `<p role="status" aria-live="polite" className="flex items-center gap-1.5 rounded-lg border border-border bg-shell-sidebar-hover px-2.5 py-1.5 text-xs text-text-secondary">` dot `size-2 rounded-full ${ok ? "bg-tone-positive" : "animate-pulse bg-tone-neutral"}` + word. Move the health `useQuery` here verbatim-key `["health"]`.
- [ ] **Step 4: Run** → PASS. Commit: `git commit -m "feat(ui): restyle topbar with real status chip; retire ThemeToggle"`.

### Task 5: PageHeading + framed workspace

**Files:**
- Create: `frontend/src/components/PageHeading.tsx`
- Modify: `frontend/src/App.tsx` (AuthLayout)
- Test: `frontend/src/components/PageHeading.unit.test.tsx` (new)

**Interfaces:**
- Consumes: `NAV_ITEMS` (Task 2 codes), `NavItem.code`.
- Produces: `<PageHeading />` — no props. Renders (per spec §4.8): `<nav aria-label="Breadcrumb">` Link `Dashboard / {title}` (non-dashboard only), `<h1>` title, optional description, right side: module chip (`{code}` in `bg-brand-accent-soft text-brand-accent-ink font-mono`) + `<time dateTime={yyyy-mm-dd}>` date pill (`weekday short, day numeric, month short, year numeric` en-IN). `titleFor(pathname)`: exact `NavItem.path` match → label; else longest NAV_ITEMS path where `pathname.startsWith(path + "/")`; else title-cased first segment. Dashboard route: title `"Welcome back"` (keeps the AppShell route test green), no breadcrumb, no chip.

- [ ] **Step 1: Failing tests:**

```tsx
it("renders the dashboard title without breadcrumb or chip", → /dashboard → h1 "Welcome back", no link)
it("renders breadcrumb + route title elsewhere", → /patients → h1 "Patient Registration", link "Dashboard / Patient Registration" → /dashboard, chip "PR")
it("falls back to the longest prefix match for sub-routes", → /admin/roles? — NOT a NavItem path… // actually /admin/users is; use /admin/departments → "Departments")
it("exposes the current date as <time>", → getByText(/,\s*\d{4}$/) — text ends with year; element tag assert container.querySelector("time"))
```
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: App.tsx AuthLayout** — canvas + frame (mock §4.10), below-lg unchanged behaviour:

```tsx
<div className="min-h-svh bg-canvas-dashboard text-foreground lg:px-[clamp(0px,4vw,44px)] lg:py-[clamp(0px,2vw,22px)]">
  <div className="lg:mx-auto lg:max-w-[1500px] lg:overflow-clip lg:rounded-[20px] lg:border lg:border-border lg:shadow-[var(--mc-shadow,0_18px_48px_rgba(45,72,82,0.10))] lg:h-[calc(100svh-2rem)] lg:flex">
    <header (unchanged sticky below lg; at lg static): className adds "lg:static">
    <div className="flex ... lg:h-full">  // sidebar h-full at lg (drop sticky offset bit via lg: overrides)
      <AppSidebar/AppSidebarDrawer (unchanged use)>
      <main className="min-w-0 flex-1 px-4 py-6 md:px-8 lg:px-6 lg:py-5 lg:overflow-y-auto">
        <PageHeading />   // INSIDE main, before Outlet
        <Suspense fallback=…><Outlet /></Suspense>
      </main>
    </div>
  </div>
</div>
```
Adapt to the existing JSX layout (the old wrapper had header outside `.flex`); keep drawer logic + `useSystemThemeSync` untouched. `--mc-shadow` registered as `--color-mc-shadow`? Shadow as arbitrary value with literal fallback is fine — prefer registering `--shadow-shell` on `:root` (both themes) in theme.css Task 1: light `0 20px 60px rgba(45,72,82,0.12)`, dark `0 20px 60px rgba(24,39,57,0.22)`, and use `shadow-(--shadow-shell)` v4 arbitrary-syntax? Use the bracket form `lg:shadow-[var(--shadow-shell)]` (works in v4).
- [ ] **Step 6: Full test run** `npm run test` → fix any shell fallout. **Step 7: Commit** `git commit -m "feat(ui): add PageHeading + Medicore framed workspace"`.

### Task 6: Screen sweep — one h1 per route

**Files:**
- Modify (remove own `h1` + header description blocks + adjust root padding where PageHeading owns the header): `modules/admin/Users.tsx`, `modules/admin/Roles.tsx`, `modules/admin/AuditLog.tsx`, `modules/admin/DepartmentsWardsBeds.tsx`, `modules/patient_registry/PatientRegistration.tsx`, `modules/patient_registry/PatientList.tsx`, `modules/patient_registry/VerificationQueue.tsx`, `modules/setup/SetupWizard.tsx`, plus any file the grep in Step 1 adds.
- Demote to `h2` (route IS a detail of a listed parent): `modules/patient_registry/PatientDetail.tsx` (UHID heading keeps mono styling + all info).
- Tests affected: module integration tests asserting old headers (`admin.integration.test.tsx`, `patient.integration.test.tsx`, `setup.integration.test.tsx`) → update name-level assertions to the new element/level.

- [ ] **Step 1: Inventory** — `grep -n "<h1" frontend/src/modules` (and components/) → list; sweep each: the header copy (title/description) moves INTO nothing — PageHeading shows route label; description text worth keeping is re-homed as the section intro the screen already had below the header (copy verbatim, keep aria structure). Screens under parent routes that ARE in NAV (e.g. /patients/* subroutes of "Patient Registration") get the breadcrumb fallback title; PatientDetail demotes as above.
- [ ] **Step 2: Failing/updated tests first** — per module: change `getByRole("heading", { name: X, level: 1 })`-style assertions to the new level/name as swept (write before editing).
- [ ] **Step 3: Sweep** — one file at a time; run `npm run test -- src/modules/admin src/modules/patient_registry src/modules/setup` — green per file before the next.
- [ ] **Step 4: Commit** `git commit -m "refactor(ui): unify page headers under PageHeading"`.

### Task 7: Dashboard — Medicore modern layout

**Files:**
- Modify: `frontend/src/modules/dashboard/DashboardView.tsx` (full rewrite)
- Modify: `frontend/src/modules/dashboard/dashboard.fixture.ts` (trim + new exports)
- Modify: `frontend/src/modules/dashboard/dashboard.unit.test.ts` (retarget)
- Modify: `frontend/src/modules/dashboard/DashboardView.integration.test.tsx` (retarget)

**Interfaces:**
- Consumes: `fixtureOpdVolume` (kept, dual series = mock's two bar series), `NAV_ITEMS` codes + `isNavItemDisabled` (Task 2), brand/chrome/chart tokens (Task 1).
- Produces fixture exports (unit-tested contract):
```ts
export interface NewPatientRow { uhid: string; name: string; department: string; time: string; status: "confirmed" | "pending"; }
export const fixtureNewPatients: NewPatientRow[];          // ≥5 rows, unique uhids, plausible mixture
export const fixtureMinis: Array<{ label: string; value: string }>;  // exactly 2: IPD occupancy, Lab orders
export const fixtureCalendarEvents: Array<{ time: string; title: string }>;  // 2 demo events
export const fixturePatientsTotal = 26710;                 // chart headline
export function calendarMonthCells(date: Date): Array<Date | null>; // 42 cells (6×7), Sunday-first, null = other-month
```

- [ ] **Step 1: Unit tests first** (dashboard.unit.test.ts — replace stats/donut assertions):

```ts
fixtureNewPatients: >=5, unique hud… uhids, every status in {confirmed,pending}
fixtureMinis: exactly 2, labels unique
calendarMonthCells(new Date(2026, 9, 22)): length 42; cells containing day 22 flagged; the cell at index (weekdayOf(new Date(2026,9,1)) === 4 ? 4+21 : …) simplicity: assert number of day-1 occurrences === 1 (no duplication) and weeks === 6
fixtureOpdVolume: 7 entries, every a/b positive int
```
- [ ] **Step 2: Run** → FAIL (new exports absent).
- [ ] **Step 3: Fixture** — implement (synthetic values; no PHI — names are obviously demo like today's; scrub colour hex fields gone with deleted exports). Delete: `fixtureStats`, `fixtureDonutBeds`, `fixtureKpis`, `fixtureBedOccupancy`, `fixtureEmergencyAcuity`, `fixtureEmergencyFlow`, `fixtureOtSchedule`, `fixtureAlerts`, `fixtureAdmissions`, `fixtureFunnel`, `fixtureDepartments`.
- [ ] **Step 4: Unit tests run** → PASS.
- [ ] **Step 5: Rewrite DashboardView.tsx** (mock ModernDashboardView mapping, spec §2.6 + §4.6/§4.7/§4.12):

```
<div className="grid gap-4">
  <div className="grid gap-3.5 lg:grid-cols-[minmax(200px,0.8fr)_minmax(340px,1.65fr)_minmax(240px,1fr)]">
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1 lg:contents? → simplest: <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-rows-[auto_auto_1fr] gap-3">
      hero <article aria-label="OPD today">: className="sm:col-span-full rounded-xl bg-primary text-primary-foreground p-5 grid grid-cols-[auto_1fr] gap-3 shadow-...">
        chip: size-9 rounded-lg border border-foreground/20 bg-white/40?? NO — token: bg-[rgba(255,255,255,0.48)]... hardcoded-ish: use bg-background/40 with backdrop? keep literal white-mix as bg-white/40 utility (allowed: white is not palette hardcode? It IS a colour literal. Use `bg-background/40` token (background=canvas white-ish) + text-primary-foreground.
        value 1842 = fixtureOpdVolume.reduce(a) formatted; label "OPD Registrations today (demo)"; foot: <Badge> Demo data + "▲ 8% vs yesterday" text-tone… on green bg use text-primary-foreground /90 (AA fine)
      minis <article aria-label=…> ×2: bg-surface-subtle? design: bg-[var(--surface)] bordered — bg-background border-border rounded-xl p-4 text-center; value font-display text-2xl text-brand-accent-ink; label text-sm text-muted-foreground
    </div>
    <section aria-label="Total Patients trend" className="rounded-2xl border border-border bg-card p-5">
      heading div: <span className="text-sm text-muted-foreground">Total patients</span> <strong className="font-display text-[22px]">26,710</strong> + <select aria-label="Chart range"> This year/This month → switches fixtureOpdVolume.reduce vs slice(-7)数据的?? single weekly fixture → options "This week"(7 bars) and "Last 3 days"(slice(-3)) — REAL behaviour on fixture data
      <div className="chart legend"><span>New</span><span>Returning</span></div>
      <div className="mt-3 flex h-[150px] items-end gap-2 border-b border-border bg-[repeating-linear-gradient(to_bottom,transparent_0,transparent_35px,calc(var(--border)*?)…)] → simpler: bg none; use CSS class defined in globals (port .bar-chart/.bar-group/.bar/.primary-bar uses bg-brand-accent; .secondary-bar = bg-brand-accent/40; small labels 10px font-mono text-muted-foreground -mb-
        bars: height % = value/max*100 (style={{height}}) — role="img" aria-label per group "Mon 04: new 42, returning 38"
      </div>
    </section>
    <section aria-label="Calendar" className="...card p-5"> "October 2026" (toLocaleDateString month+year), button "Today" onClick setToday(); week header S–S; 6×7 grid of buttons (button for real dates? buttons weekend? plain <span> for dates, <button aria-pressed> for each selectable day — pick: buttons for every in-month day, aria-pressed selected, onClick selects); events under it from fixtureCalendarEvents (event-dot bg-brand-accent)
    </section>
  </div>
  <section aria-label="New patients" className="rounded-2xl border border-border bg-card overflow-hidden">
    toolbar: <h2 text-…>New patients</h2> <p tiny muted>Registered today</p>; right: <Input aria-label="Search patients" value onChange filters rows by uhid/name> + <Button asChild variant outline → Link /patients>View all</Link>
    <div overflow-x-auto><table className="w-full border-collapse text-sm min-w-[720px]">
      thead: UHID | Patient | Department | Registered | Status — th px-3.5 py-2.5 bg-muted text-left text-xs font-medium text-muted-foreground border-y border-border
      tbody rows: uhid font-mono text-foreground; name cell: <span size-6 rounded-md bg-brand-accent-soft text-brand-accent-ink initials> + name font-medium; status <span px-2 py-1 rounded text-xs {confirmed: bg-brand-accent-soft text-brand-accent-ink / pending: bg-tone?? amber tokens absent → use bg-muted text-muted-foreground? NO — pending needs distinct word+colour: bg-secondary text-secondary-foreground + word "Pending" (word carries meaning, colour distinct enough)}>; row hover:bg-muted/50
    </table></div>
  </section>
  <div aria-label="Module overview" className="grid gap-2 grid-cols-2 md:grid-cols-5" role="group">
    {stripIds.map(id => navItem = NAV_ITEMS.find(...) → entry.availability==="enabled" ? <Link to className="...border bg-card rounded-xl p-2.5 flex gap-2 hover:border-ring cursor-pointer"> chip {code} <strong text-xs>{label}</strong> : <button disabled title={navItemTitle} className="…opacity-60 cursor-not-allowed"> same + <span state word sr-ish visually-hidden>{navItemStateLabel}</span>}
      (stripIds = ["opd","ipd","emergency","ot","icu","lis","ris","pharmacy","insurance","emr"])
  </div>
</div>
```
All controls real: search filters state; select switches range; Today selects today. No dead links: disabled buttons for unbuilt modules carry state word + release (navItemTitle). The view ports mock proportions at plan scale (Task-level notes in spec §4.1). Keep an eye on AGENTS: icon-only button none here (all textual) — links "View all" textual ✓.
- [ ] **Step 6: Integration test rewrite:**

```tsx
it("shows the modern panels"): getByText("Total patients"), "New patients", module strip role group
it("keeps the demo-data pill", getAllByText(/demo data/i) ≥1)
it("search filters the table rows"): value becomes `${fixtureNewPatients[0].uhid}` → table shows exactly the row(s) matching (driven by the fixture, not a name literal)
it("chart range select switches series length"): select "Last 3 days" → 3 bar groups (getAllByRole("img")) hmm bar groups role img per group — assert count 3
```
- [ ] **Step 7: npm run test** full → green. **Step 8: Commit** `git commit -m "feat(dashboard): rebuild on the Medicore modern layout"`.

### Task 8: Full gate + doc sync

- [ ] **Step 1:** `npm run check` (from `frontend/`) — lint + typecheck + all tests.
- [ ] **Step 2:** Backend drift proof (from `backend/`): `python -m ruff check . ../tests` clean; `python -m pytest` passes.
- [ ] **Step 3:** Manual smoke `npm run dev`: /dashboard, /patients, /admin/users in BOTH themes; 375px, 768px, 1024px, 1440px widths (spec §2a).
- [ ] **Step 4:** README/docs cross-check per AGENTS §3 doc-sync — README tech-stack + Dependency version guidance unchanged except fonts line (Task 1); confirm no pattern/§ sections stale.
- [ ] **Step 5:** Final commit if stray files: `git status` clean except user's `vite.config.ts` + backend migration 0012 (leave).

## Review follow-ups — 2026-10-22 (post-plan, code-review driven)

Verdicts received: "not ready to merge" (C1 dark-mode contrast) + user's live bug "dashboard is inside another wrapper". All resolved on the branch:

- **e934697** `fix(ui)`: framed shell restored to the mock's single-scroll model — frame `min-h` + flex-col, rail/content in flow, no `main` inline scroll. Root cause of the wrapper bug (Task-5 over-claimed "only the content column scrolls"; the spec never prescribed it). Pinned by a 23rd AppShell test; live-verified post-HMR (doc 1481 > viewport 679, `main` non-scrollable, one page scroll).
- **ec781f6** `fix(a11y)`: C1+I3 — every text-bearing `bg-background` surface re-paired to `bg-card` (9 input strings, kiosk ×4, login/MFA containers, dashboard minis + chart select); new CI pair pins (foreground/muted on `--card`, both themes). Hero chip stays `bg-background/40` (full-ink contrast 6.3/6.8:1).
- **1407442** `fix(a11y)`: I1 drawer renders `SidebarFooter` (theme control reachable on md-); I2 hero drops `/80`; M2 DM Mono loads 700.
- **Deferred** (design-intent / pre-existing): M1 collapsed rail hides the switcher; M3 drawer has no Escape/focus handling.
- Live dark-mode proof through the drawer itself: mini bg = `rgb(49,60,78)` (`--card`), hero text = `rgb(5,61,48)` (full ink), theme round-trip restored to System.
- Full gate green at 193/193 + ruff/unit backend green — co-verified while the user's own WIP (`patient.api.ts`, `PatientRegistration.tsx`, patient tests, `vite.config.ts`, migration 0012) passes in the same worktree; those files remain **uncommitted by request** (my one `bg-card` line rides inside the user's `PatientRegistration.tsx` rewrite and lands with their commit).
- **25a4560** `feat(ui)`: full-bleed at every width — user reversed the framed shell after seeing it at 1920px; chrome classes stripped from `App.jsx` shell, shell toned with `--shell-sidebar`, invariant test flipped to a no-chrome pin, spec §4.10 marked REVERSED. `--canvas-dashboard` stays defined but unused by the shell.
- **4d8a7ad** `fix(ui)`: topbar actions (health chip, demo badge, bell, user menu) wrapped in a pinned cluster (`ml-auto`, mirroring the mock's `.topbar-actions`) so the bar's content spans the full shell width; search stays by the selects. Live-measured: menu right edge = header edge − padding.
- Context7: `/websites/ui_shadcn` (prior session; no new library API in these fixes). Skills: systematic-debugging (wrapper root cause), receiving-code-review (review fixes).
