# Medicore restyle — design (shell + all module screens)

Source of truth: Figma "SaaS HIMS Dashboard" (Medicore), local export
`C:\Users\USER\Downloads\SaaS HIMS Dashboard` (`src/App.tsx`, `src/index.css`).
Approved scope: the application shell AND the look of every module screen.

## 1. What the design provides

- **Token themes** — `.theme-light` / `.theme-dark` variable sets:
  - light: canvas `#dbe5e8`, shell `#ffffff`, sidebar `#fbfdfd`, topbar `#ffffff`,
    content `#edf4f5`, surface `#ffffff`, surface-soft `#f4f8f8`, line `#e2ebec`,
    text `#17212b` / soft `#617078` / faint `#98a6ab`,
    accent `#18c58d`, accent-strong `#0eac77`, accent-soft `#dff8ef`, soft shadow.
  - dark: canvas `#cbd7da`, shell `#1f2a40`, sidebar `#1c2940`, topbar `#283a56`,
    content `#202a40`, surface `#2a3a55`, surface-soft `#24334c`, line `#334761`,
    text `#f4f7fa` / soft `#aebbc9` / faint `#718198`,
    accent `#18c58d`, accent-strong `#28d79d`, accent-soft `rgba(24,197,141,.12)`.
- **Fonts** — DM Sans (display), Inter (body), DM Mono (codes/numbers) via
  Google Fonts (CSS import; NOT an npm dependency).
- **Shell** — 222px sidebar (brand block, section labels, nav-code chips,
  active side-bar + accent-soft fill, theme switcher + version footer),
  72px topbar (global search with ⌘K, profile block with name+role), and a
  page-heading (breadcrumb "Dashboard / X", h1, description, date pill,
  module-indicator chip).
- **Dashboard (active "Modern" variant)** — green hero metric (OPD) + two mini
  metrics; "Total Patients" CSS bar chart (dual series); calendar card;
  "New patients" table card (avatar chip, mono UHID, status pill); module strip
  (10 nav-coded buttons).
  (The export's other `DashboardView`-style variant is the inactive navy
  operations mock — explicitly NOT ported.)

## 2. Decisions (and what we deliberately don't port)

1. **Tokens do the reskin; screens keep their logic.** Mediflow screens consume
   shadcn semantic tokens (`bg-card`, `border-border`, `bg-background`,
   `bg-primary`, `text-muted-foreground`, `border-input`, `bg-shell-*`).
   We re-point those token VALUES to the Medicore palette in
   `styles/theme.css` + `styles/globals.css` (light `:root` / `.dark`), add the
   new Medicore shell variables (`--mc-shell`, `--mc-sidebar`, `--mc-topbar`,
   `--mc-content`, `--mc-surface-soft`, `--mc-line`, `--mc-accent(-strong|-soft)`,
   `--mc-text*`, `--mc-app-bg`, `--mc-shadow`) plus font tokens
   (`--font-display`, `--font-mono`). No screen internals are ported from the
   mock: the mock's data is invented; our screens are real.
   - `--primary` becomes the Medicore green `#18c58d`; `--primary-foreground`
     becomes dark green `#073c2f` (design's own button recipe) because
     white-on-`#18c58d` fails AA. Brand primary retires the fixed teal
     `hsl(174 83% 25%)` — part of adopting this design, called out here for
     approval.
   - Design's literal `#131f35`-era hardcoded classes are NOT copied. A sweep
     replaces any remaining hardcoded navy/blue hex classes (`bg-[#…]`,
     `text-slate-*`, old `--shell-*` navy values) with tokens.
2. **Scale correction (mandatory).** The mock is a zoomed-out 1500px artboard:
   its 6–11px type is unreadable at 1:1. Port the class set at ≈1.55×
   (8px→12px, 9px→14px, 11px→16–17px; card padding 14→22px, radius 13→16px)
   keeping all proportions, layout, and spacing relationships.
3. **Sidebar** — restyled in place, same component (`AppSidebar.tsx`):
   brand block (32px "M" mark, "MEDIFLOW" wordmark, "Hospital Information
   System"), "Main menu" + renamed "Configuration & setups" section label
   (current "Settings" group; same items), nav-code chips via a new `code`
   field on `NavItem` (codes below), active = accent-soft fill + 3px accent
   bar, hover = surface-soft collapsed rail keeps working (nav codes alone, no
   labels), disabled entries keep release tag + state word (not colour alone),
   drawer unchanged structurally.
   - Codes — main: DB, PR, OP, IP, EM, ER, IC, OT, LB, RD, RX, BB, IN.
     settings: BI, TF, CL, QO, CA, DQ, AL, AS, RE, UR, DE, WB, FS, CH, RC,
     QP, AQ, AU, NO, AB, IG, PT.
4. **Topbar** — restyled in place (`AppHeader.tsx`): keeps every existing
   control (mobile nav trigger, collapse toggle, tenant/facility selects
   — design.md §5.2 forbids hiding them — patient search + Ctrl K hint,
   Live/Demo badge, notifications, profile dropdown with sign-out), painted in
   Medicore tokens instead of navy. The topbar ThemeToggle moves into the
   sidebar footer as the design's Light/Dark segmented switcher
   (`aria-pressed`, wired to the same `themeStore.setPreference`; "system"
   remains respected until the user makes an explicit choice — identical to
   today's behaviour). ThemeToggle.tsx is removed when unused. The mock's
   "Operational" status chip is skipped: we already surface real
   connection/demo state, and a static "Operational" chip would be a fake
   health signal.
5. **Page heading** — new `PageHeading` component rendered once by the
   authenticated layout: h1 = route's nav label, breadcrumb
   "Dashboard / {title}" (links home) on non-dashboard routes, date pill,
   module-indicator chip on module routes. Per-screen duplicate h1s found by
   grep are dropped in the sweep.
6. **Dashboard** — rebuilt as the Modern layout, same data contract as today
   (fixture + Demo-data pill; live wiring stays deferred and labelled):
   hero OPD metric + 2 minis, Total Patients bar chart (pure CSS bars, dual
   series — no chart library), calendar card (display-only demo), New patients
   table (fixture rows, UHID in mono, status pills), module strip driving
   router navigation for the ten modules. Panel titles stay
   behaviour-testable (accessible names).
7. **Accessibility** — CI contrast test (`styles.unit.test.ts`) updated to the
   shipped pairs: rail foreground/section text on sidebar, topbar controls on
   topbar, active-label pair, hover boundary ≥1.05. New rule from the design:
   `#98a6ab`/`#718198`-strength text is decorative-only — anything carrying
   information uses the `--text-soft`/`--text` tier (the mock's faint tier
   measures ~2.5:1 and cannot carry meaning). Focus rings switch from
   `ring-white` (only valid on the old navy) to a token ring valid on both
   themes.
8. **Files touched** — `styles/globals.css`, `styles/theme.css`,
   `lib/navigation.ts` (add `code`), `components/AppSidebar.tsx`,
   `components/AppHeader.tsx`, new `components/PageHeading.tsx`,
   `App.tsx` (layout + route wiring), `modules/dashboard/DashboardView.tsx` +
   `dashboard.fixture.ts`, legacy-colour sweep across `modules/**` and
   `components/**`, README.md tech-stack line for the web-font asset.
   No backend change. No dependency change (Google Fonts is an external CSS
   import, documented per AGENTS §3 doc-sync rule).
9. **Named deferrals** — OPD/IPD/LIS/… master-data real data (backends are R2+,
   nav stays availability-gated); calendar stays a demo display; dashboard
   patient table stays fixture-fed under the existing Demo-data pill contract
   (live `/patients` wiring is a separate follow-up if asked).

## 2a. UI/UX Pro Max findings (applied)

Runs against the skill database (design-system for "hospital management
clinical SaaS dashboard", color and shadcn stacks):

- The generated default system (Glassmorphism style, trust-blue `#2563EB` +
  orange CTA, Plus Jakarta Sans) was **rejected as a palette** — the user
  selected the Figma Medicore design as source of truth. Only its
  product-type match (dense dashboard, high density dial) confirms the layout
  direction.
- **Adopted into the spec:** (1) complete `:root` and `.dark` semantic token
  schemes with `@theme inline` mappings, no hardcoded palette colours in
  components (shadcn theming rule — matches decision 1); (2) button-fill
  label contrast ≥4.5:1 — Medicore's `#073c2f` on `#18c58d` measures ≈5.5:1,
  and the CI test pins it; (3) motion kept subtle: the mock's `status-pulse`
  keyframe gets a `prefers-reduced-motion` guard and renders static;
  transitions 150–300ms; (4) visible focus states on all interactive ports
  (focus-ring token valid on both themes, replaces `ring-white`);
  (5) cursor discipline: ported clickables (`module-strip`, `config-option`
  style surfaces) are real `<button>`/`<Link>` elements — Tailwind v4 preflight
  makes them cursor-default, so the ported classes add `cursor-pointer`;
  (6) all icons stay `lucide-react` SVG — no emoji-as-icon from the mock;
  (7) responsive verification at 375 / 768 / 1024 / 1440 px in addition to the
  existing tablet collapse behaviour.

## 3. Verification plan

- `npm run check` (lint + typecheck + tests) from `frontend/`.
- Updated: `styles.unit.test.ts` (new pairs), `AppShell.integration.test.tsx`,
  `DashboardView.integration.test.tsx` + `dashboard.unit.test.ts`
  (new titles/panels), `navigation.unit.test.ts` (codes; group label),
  small new test asserting every `NavItem.code` is a unique 2-letter code.
- Manual: `npm run dev`, visit dashboard + one real screen per theme.
- Backend untouched: `python -m ruff check . ../tests` and `python -m pytest`
  re-run only to prove no drift.

## 4. Builder-check resolutions (final word for the implementer)

Results of the simulated build (subagent review). Nothing below is open.

1. **Concrete type scale (replaces "≈1.55×").** The rail does NOT scale
   uniformly — it fits: sidebar stays **240px wide** (repo width; AGENTS §5),
   topbar stays **h-16 / 64px** (no sticky-offset desync: the existing
   `sticky top-16` / `h-[calc(100svh-4rem)]` pair in AppSidebar/AppHeader is
   untouched). Final sizes: rail section label 11px uppercase; nav label 14px
   with `truncate` + `title` (the one long label, "Assessments (NQAS/NABH)",
   truncates by design); nav-code chip 26px box, 10px DM Mono; footer
   switcher 13px; version line 11px mono. Topbar: search 14px, status/pill
   text 12px, profile name 14px / role 11px. Page heading: h1
   `clamp(22px, 2vw, 28px)` DM Sans; description 14px; breadcrumb 13px; date
   pill + module chip 13px. Dashboard: hero value 30px, hero label 13px, mini
   values 24px, card-heading 13px/22px, bars labelled 10px mono, table
   13px, module strip 12px/10px, calendar numerals 12px mono. Card paddings
   scale ≈1.4× (mock 14–17px → 20–24px), radii 10/13px mock → 12/16px.
2. **Chrome is theme-scoped now.** The `--shell-*` set stops being
   navy-everywhere constants: values are re-pointed per theme
   (`:root` → Medicore light chrome, `.dark` → Medicore dark chrome) and
   AppHeader/AppSidebar drop every hardwired white-on-dark utility
   (`text-white`, `bg-white/10`, `border-white/20`, `ring-white`,
   `hover:bg-white/10`) for token classes. The two CI guards that exist to
   enforce the OLD invariant (`styles.unit.test.ts` "theme independence";
   AppShell "does not colour the rail with theme-scoped sidebar tokens") are
   deliberately INVERTED: both suites now assert chrome tokens exist in
   `:root` AND `.dark`, with passing pairs in both.
3. **Contrast tiers (what CI pins).** Pair list for `styles.unit.test.ts`:
   sidebar-foreground/sidebar, sidebar-subtle-bumped-to-soft-tier/sidebar,
   topbar-foreground/topbar, primary-foreground/primary (≈5.5:1),
   active-label pair, hover-fill boundary >1.05 (hover fill tuned to pass —
   implementer picks the exact deeper grey, the test decides), and the
   green-ink text tier on light surfaces (below). Because the mock's faint
   tier is ~2.4–3.7:1, **any text that carries information uses the
   soft-or-stronger tier**: rail section labels, stats sublabels, table
   headers all sit on `--text-soft`/`--text`. `--text-faint` is decorative
   only. Green-as-text on light surfaces: fill greens `#18c58d`/`#0eac77`
   are fills/graphics only; text greens use `--accent-ink` (~`#067a54`,
   ≥4.5:1 on white and on `--accent-soft`). Dark theme keeps the mock's
   lighter `#28d79d` for text (passes on the dark surfaces).
4. **Sweep scope (corrected — there are no `bg-[#…]`/`text-slate-*` classes
   to hunt).** The real hardcoded surfaces: AppHeader's white set (resolution
   2), DashboardView's funnel/donut hexes and `hsl(174 83% 30%)`
   → `--chart-*`/tone tokens, fixture colour hexes, and `bg-green-600` /
   `bg-amber-500` live badge → existing `tone-*` tokens (always paired with
   a word/arrow, never colour alone).
5. **Theme switcher is three states.** Sidebar footer renders
   Light | Dark | System as the mock's segmented control (one extra segment
   beyond the mock), wired to `themeStore.setPreference` — preserves the
   store's three-state contract, today's localStorage key, and the
   `AppShell` ThemeToggle coverage (assertions move; `ThemeToggle.tsx`
   retires, single control).
6. **The mock's "Operational" chip becomes REAL.** The `/health` query that
   today lives on the dashboard header band moves into the topbar status
   chip: green dot + "Operational" when healthy, amber + state word when
   degraded/unreachable, 30s `refetchInterval` preserved (AppShell test
   pairing moves with it). The Live/Demo badge stays beside it.
7. **No dead links anywhere.** Module strip buttons, and every card CTA the
   mock wires to unbuilt modules, render via `isNavItemDisabled`:
   enabled targets navigate; notEnabled/disabled render a disabled button
   carrying the state word + release tag. Hero metric is a display card, not
   a button. The mock's Emergency ".nav-alert 6" badge is dropped — there is
   no real count feed, and AGENTS forbids fake state. Table "View All" →
   `/patients` (real); calendar "Add New" control dropped.
8. **PageHeading data source.** h1 = best `NavItem.label` match
   (exact path, else longest path-prefix, else route segment title-cased);
   breadcrumb "Dashboard / {title}" links home on non-dashboard routes; date
   pill is a real `<time>` element (current date), NOT the mock's fake
   button. Module chip = the single-accent scheme
   (accent-soft fill + accent-ink code, resolution 3) — the mock's ten
   per-module decorative colours are dropped (would need ten tokens for
   zero information). Per the sweep, each implemented screen drops its own
   `h1` + description + root padding (Users, Roles, AuditLog,
   DepartmentsWardsBeds, patient_registry screens, setup, dashboard bundle);
   PatientDetail's UHID heading demotes to a styled h2 (information kept).
9. **Chips replace icons on the rail.** The shell renders nav-code chips,
   not Lucide icons (the design's identity). `NavItem.icon` stays in the
   model (other consumers/tests rely on it) but is not rendered by the
   chrome; the mobile drawer uses the same chip style.
10. **Frame — REVERSED 2026-10-22.** The framed shell (canvas backdrop +
    rounded bordered `min(1500px, 100%)` frame with soft shadow) shipped
    per the mock, but the **user reversed it**: the shell now runs
    **full-bleed at every width** — no canvas padding, no frame chrome;
    the shell tone is `--shell-sidebar` edge to edge, one page scroll,
    sticky topbar. The canvas token stays defined (palette record) but is
    unused by the shell.
11. **Version footer string.** Real stack line, not the mock's fake
    "v4.2.1 · HL7 FHIR R4": `Mediflow OS · React 18 · Django 5.2`.
12. **No dead controls.** Dashboard card controls only exist where a real
    behaviour backs them: table search filters the fixture rows; the chart
    range select switches between ranges present in the fixture data; the
    mock's decorative "Filters" button is dropped. The date pill is `<time>`
    (resolution 8).
13. **Fonts mechanics.** The existing `index.html` Google Fonts `<link>`
    gains DM Sans + DM Mono (one request; Inter + Noto Sans Devanagari
    stay). `--font-display: 'DM Sans'`, `--font-mono: 'DM Mono'` (mono for
    codes/numerals; JetBrains Mono retires), body stays Inter. README gets
    the tech-stack line (AGENTS §3 doc-sync; no package.json change).
14. **Out-of-shell surfaces.** Login/MFA inherit the re-pointed tokens
    automatically (their CTA turns the Medicore green — accepted).
    EXCLUDED by design: kiosk `TokenDisplay` (standalone), print `OpSlip`
    (print stylesheet).
    Orphaned fixture exports (`fixtureStats`, donut series) are deleted
    with their tests; the unit test target moves to the pieces the Modern
    layout actually uses (bar series, calendar grid, strip data).
15. **Test-harness note.** `styles.unit.test.ts`'s `token()` helper matches
    hex only; the dark `--accent-soft` (`rgba(...)`) needs the helper
    extended or the pair asserted via a computed mix — implementer's small
    job, listed here so it isn't a surprise.
