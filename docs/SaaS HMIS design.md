# SaaS HMIS — Product UI Design System

**Version:** 0.2 (draft)  
**Date:** 3 Oct 2026  
**Status:** For review  
**Purpose:** Visual and product-level UI contract for the SaaS HMIS web application.

### Change log

| Version | Date | Change |
|---|---|---|
| 0.2 | 3 Oct 2026 | Incorporated the supplied 1536×1024 HMIS dashboard reference: dark navy shell, blue active navigation, six-card KPI strip, three-panel analytics row, OT schedule, critical alerts, admissions/discharges, patient-flow funnel and department-performance table. |
| 0.1 | 3 Oct 2026 | Initial visual design system. |

## 1. Design direction

The product is a hospital operating application, not a marketing dashboard. The visual system must communicate clinical reliability, speed, hierarchy and auditability.

**Visual character**

- Clinical, enterprise and restrained.
- High information density without visual clutter.
- White/neutral work surfaces with teal as the primary brand colour.
- Strong typographic hierarchy; colour is supporting information, never the only signal.
- No decorative gradients, glassmorphism, excessive shadows, oversized rounded cards, animated backgrounds or consumer-app styling.
- Use subtle borders, compact spacing and predictable alignment.
- Every screen must work at 1366×768 and support tablet ward use.

**Design decision:** Use a restrained clinical enterprise aesthetic because the source documents prioritise busy clinical staff, data integrity, accessibility and long-session readability over visual novelty.

The Architecture establishes React + TypeScript + Vite, Shadcn UI/Radix, Tailwind CSS v4, Lucide icons and inline SVG charts as the frontend foundation. Do not introduce another UI kit or chart library. [Architecture §4, §14.1]

## 2. Brand identity

### 2.1 Brand concept

**Brand idea:** one connected system for complete care.

The application should visually connect patient identity, encounters, clinical workflows, billing and Quality OS rather than making modules look like unrelated products.

### 2.2 Primary colour

Architecture fixes the primary colour as teal `#0f766e` / HSL `174 83% 25%`. [Architecture §14.1]

| Token | Light value | Dark value | Usage |
|---|---|---|---|
| `--primary` | `hsl(174 83% 25%)` / `#0f766e` | `hsl(174 83% 35%)` | Primary actions, active navigation, focus accents |
| `--primary-foreground` | `#ffffff` | `#ffffff` | Text/icons on primary |
| `--background` | `#f8fafc` | `#0b1220` | Application background |
| `--foreground` | `#0f172a` | `#f8fafc` | Main text |
| `--card` | `#ffffff` | `#111827` | Cards, panels, dialogs |
| `--card-foreground` | `#0f172a` | `#f8fafc` | Card text |
| `--muted` | `#f1f5f9` | `#1e293b` | Secondary surfaces |
| `--muted-foreground` | `#475569` | `#cbd5e1` | Secondary text |
| `--border` | `#e2e8f0` | `#334155` | Borders/dividers |
| `--input` | `#cbd5e1` | `#475569` | Input borders |
| `--ring` | `#0f766e` | `#2dd4bf` | Keyboard focus |

### 2.3A Screenshot-informed shell palette

The supplied dashboard reference establishes the intended application-shell visual language: a dark navy left rail and top bar, a very light cool dashboard canvas, white content cards, blue navigation emphasis, and teal/green operational status. The architecture-defined brand primary remains teal `#0f766e`; blue is an operational/navigation accent, not a replacement for the brand primary.

| Token | Value | Use |
|---|---|---|
| `--shell-sidebar` | `#132134` | Persistent left navigation |
| `--shell-topbar` | `#153047` | Global top bar |
| `--shell-active` | `#0B75E5` | Active navigation item and selected dashboard controls |
| `--canvas-dashboard` | `#F5F9FD` | Dashboard/application canvas |
| `--surface` | `#FFFFFF` | KPI cards, charts, tables, panels |
| `--surface-subtle` | `#F8FBFD` | Secondary panel backgrounds |
| `--text-primary` | `#0F172A` | Titles, KPI values, primary content |
| `--text-secondary` | `#475569` | Supporting content |
| `--brand-primary` | `#0F766E` | Primary product action, active clinical state, brand accents |

Contrast references: white on `#132134` = 16.22:1; white on `#0F766E` = 5.47:1; `#0F172A` on `#F5F9FD` = 16.88:1. The active blue `#0B75E5` with white text is 4.48:1, so normal-text labels on active blue must use at least 14 px bold or use the active state as a larger UI component/selected control rather than small body text.

### 2.3 Semantic status palette

These are product design decisions built around the required semantic states in the UI/UX specification. They must be paired with text, icons or patterns.

| Semantic state | Foreground | Soft surface | Meaning |
|---|---|---|---|
| Critical | `#b91c1c` | `#fef2f2` | Immediate attention / clinical or system criticality |
| Warning | `#a16207` | `#fefce8` | Action required, risk, overdue |
| Success | `#15803d` | `#f0fdf4` | Completed, valid, within target |
| Info | `#1d4ed8` | `#eff6ff` | Informational state |
| Unsynced | `#7c3aed` | `#f5f3ff` | Local queue not confirmed by server |
| Provisional | `#c2410c` | `#fff7ed` | Temporary/unverified value or patient record |
| Locked | `#475569` | `#f1f5f9` | Immutable closed-period/value state |

**Contrast checks:** primary text white on `#0f766e` = **5.47:1**; white on critical red `#b91c1c` = **6.47:1**; white on success green `#15803d` = **5.02:1**; white on info blue `#1d4ed8` = **6.70:1**; white on slate `#475569` = **7.58:1**. Dark text `#0f172a` on `#f8fafc` = **17.06:1**. These meet WCAG AA for normal text.

### 2.4 Logo treatment

**Desktop:** logo at 28–32 px height, icon/mark plus product wordmark.  
**Login:** logo centred above the sign-in card; maximum visible width 220 px.  
**Kiosk:** logo reduced to 24–28 px so token numbers dominate.  
**Print:** monochrome-safe version required.

Do not place the logo inside a large coloured hero banner.

## 3. Typography

### 3.1 Font stack

Primary Latin stack:

```css
font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
  "Segoe UI", sans-serif;
```

Devanagari-capable fallback:

```css
font-family: Inter, "Noto Sans Devanagari", ui-sans-serif, system-ui, sans-serif;
```

Mizo and other Latin text uses the primary stack. Scripts not covered by the selected webfont fall back to the system UI font.

### 3.2 Type scale

| Role | Size | Weight | Line height |
|---|---:|---:|---:|
| Display | 32 px | 700 | 1.15 |
| Page title | 24 px | 700 | 1.2 |
| Section title | 18 px | 650 | 1.3 |
| Card title | 16 px | 600 | 1.35 |
| Body | 14 px | 400 | 1.5 |
| Compact body | 13 px | 400 | 1.45 |
| Label | 12 px | 600 | 1.35 |
| Caption | 11 px | 500 | 1.35 |
| Numeric KPI | 28–36 px | 700 | 1.1 |
| Kiosk token | 72–120 px | 700 | 1.0 |

Use tabular numerals for tables, timestamps, counters and quality indicators.

## 4. Spacing, shape and elevation

### 4.1 Spacing

Base unit: **4 px**.

Primary spacing steps: 4, 8, 12, 16, 20, 24, 32, 40, 48 px.

Screen-level gutters: 24 px desktop; 16 px tablet.  
Card internal padding: 16–20 px.  
Dense tables: 10–12 px vertical cell padding.  
Form rows: 16 px vertical separation.

### 4.2 Radius

- Inputs/buttons: 6 px.
- Cards/panels: 8 px.
- Dialogs/sheets: 10 px.
- Status pills: 9999 px.

Do not use large 20–32 px radii on operational screens.

### 4.3 Elevation

Use borders first, shadow second.

```text
shadow-xs: 0 1px 2px rgba(15, 23, 42, 0.04)
shadow-sm: 0 1px 3px rgba(15, 23, 42, 0.08)
shadow-md: 0 8px 24px rgba(15, 23, 42, 0.10)
```

Cards on normal pages use border + `shadow-xs` at most. Dialogs use `shadow-md`.

## 5. Application shell

### 5.1 Global layout

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ LOGO  Tenant ▾  Facility ▾  Department ▾   Search ⌘K      🔔   User ▾       │
├──────────────┬───────────────────────────────────────────────────────────────┤
│ Dashboard    │ Breadcrumb / Patient context                                │
│ Registration │                                                               │
│ OPD          │ Page title                         Actions                    │
│ IPD          │                                                               │
│ EMR          │ ┌─────────────────────────────────────────────────────────┐ │
│ Billing      │ │                                                         │ │
│ Quality OS   │ │                PAGE CONTENT                              │ │
│ Reports      │ │                                                         │ │
│ Admin        │ │                                                         │ │
│              │ │                                                         │ │
│              │ └─────────────────────────────────────────────────────────┘ │
└──────────────┴───────────────────────────────────────────────────────────────┘
```

### 5.2 Header

Height: **64 px**.

Left: logo, tenant/facility selector.  
Centre/left: global command search.  
Right: notification bell, connection state when relevant, user menu.

Tenant context must remain visible after scrolling. Facility and department context must never be hidden inside only a tooltip or avatar.

### 5.3 Sidebar

Width: 240 px expanded; 72 px collapsed.

Navigation groups:

```text
WORKSPACE
  Dashboard
  Registration
  OPD
  IPD
  EMR
  Billing

QUALITY
  Quality OS
  CAPA
  Reports

ADMINISTRATION
  Users & Roles
  Departments
  Wards & Beds
  Facility Setup
  ABDM / QR
  Audit
```

R4–R7 modules appear only when enabled by tenant configuration. Disabled features should show `Not enabled` rather than exposing dead routes.

### 5.4 Patient context bar

When a patient is active, display a persistent patient banner above page content:

```text
[PROVISIONAL] UHID: ZMC-00012345   PATIENT NAME, Age/Sex   ABHA: Linked
DOB • mobile • current encounter • department
```

The banner remains visible on OPD, IPD, EMR, billing and quality drill-through pages involving patient-level evidence.

## 6. Login and authentication design

### 6.1 Login page

Route: `/auth/sign-in`

```text
┌────────────────────────────────────────────────────────────────────┐
│                                                                    │
│                         [ BRAND MARK ]                             │
│                         SaaS HMIS                                  │
│              Hospital Management Information System                │
│                                                                    │
│                  ┌────────────────────────────┐                    │
│                  │ Sign in                    │                    │
│                  │                            │                    │
│                  │ Email / User ID            │                    │
│                  │ [________________________] │                    │
│                  │                            │                    │
│                  │ Password                   │                    │
│                  │ [____________________  👁] │                    │
│                  │                            │                    │
│                  │ [        Sign in          ] │                    │
│                  │                            │                    │
│                  │ ─────── OR ──────────────  │                    │
│                  │ [ Continue with SSO       ] │                    │
│                  │                            │                    │
│                  │ Forgot password?            │                    │
│                  └────────────────────────────┘                    │
│                                                                    │
│                     Secure hospital access                         │
└────────────────────────────────────────────────────────────────────┘
```

**Visual rules**

- Background: `#f8fafc` with a very subtle tonal panel behind the form; no illustration required.
- Login card: max width 420 px; white background; 1 px border; 8–10 px radius.
- Primary button: teal `#0f766e`, full card width, 44 px height.
- SSO is secondary outline button.
- Password visibility is icon-only and requires `aria-label`.
- Error appears immediately below the relevant field, not as a generic toast alone.
- Session/tenant context is shown only after authentication.

### 6.2 MFA page

Route: `/auth/mfa`

Use six-digit OTP entry with one logical input group, auto-advance, paste support and clear remaining-attempt messaging. Do not visually imply success until the server confirms.

### 6.3 SSO page

Route: `/auth/sso`

Show identity-provider name, tenant context if already known, loading state and recovery route back to standard sign-in if allowed.

## 7. Tenant selection and onboarding

### Tenant selection

Use a searchable list/table rather than a tile-heavy design.

```text
Select hospital
[ Search hospital / facility __________________ ]

┌───────────────────────────────────────────────────────────────┐
│ Zoram Medical College & Hospital        Aizawl   Active     > │
│ District Hospital Example                District Active     > │
└───────────────────────────────────────────────────────────────┘
```

Only tenants authorised for the signed-in user are returned.

### Hospital onboarding

Platform admin uses a stepper:

`Hospital identity → Facilities → Accreditation profile → Admin user → Review → Activate`

Completion percentage remains visible. Do not expose internal database identifiers.

## 8. Web application dashboard design

### 8.0 Reference design to implement

The supplied reference image is a **1536×1024 desktop dashboard**. Treat it as the visual baseline for the authenticated application shell and executive dashboard. It establishes proportions and hierarchy, not literal sample values or fixed text.

Core characteristics to preserve:

- Left sidebar: approximately **240 px** wide, dark navy, vertically grouped navigation with compact line icons and section labels.
- Global top bar: approximately **64 px** high, dark navy, with patient search on the left/centre and facility selector, notifications and user identity on the right.
- Main canvas: cool near-white background with **24 px** page gutters.
- Header row: date/period context at left; live-data status, timestamp and date-range selector at right.
- KPI strip: **6 cards in one row** at 1536 px width; each card has icon tile, label, large numeric value, trend/value delta and a small inline SVG sparkline.
- Primary dashboard body: **three visual panels** in one row: Bed Occupancy, OPD Volume Trend, Emergency — Acuity & Flow.
- Operational body: large OT schedule table on the left and Critical Alerts list on the right.
- Lower body: Recent Admissions & Discharges, Patient Flow Funnel, Department Performance.
- Cards use white surfaces, subtle 1 px borders, small shadows and 8 px corner radius.
- The dashboard is information-dense but avoids overlapping controls; each card has one clear title/action area.

**Design decision:** preserve this reference composition because it gives Medical Superintendent/CEO users a single-screen operational overview while keeping the clinical shell consistent with the rest of the product.

### 8.1 Executive/landing dashboard

Route: `/dashboard`

The dashboard is role-aware, but the Medical Superintendent/CEO presentation in the supplied reference is the canonical visual composition.

At 1536×1024:

```text
┌─────────────────────────────── 240 px sidebar ─────────────────────────────┬──────────────────────────────────────────────────────────────────────┐
│ HIMS                          │ Search patient by UHID, name, phone, ABHA…     │ Facility ▾     🔔     User ▾                          │
│ HOSPITAL INFORMATION          ├───────────────────────────────────────────────┤
│ MANAGEMENT SYSTEM             │ Friday, 8 August 2026       ● Live Data       │
│                               │ Welcome back, Dr. [Name]       10:24 AM       │
│ MAIN MENU                     │ Real-time overview…             Today ▾        │
│  Dashboard                    ├───────────────────────────────────────────────┤
│  EMR                         │ KPI 1 │ KPI 2 │ KPI 3 │ KPI 4 │ KPI 5 │ KPI 6│
│  OPD                         │ card  │ card  │ card  │ card  │ card  │ card │
│  Patient Registration        ├───────────────┬────────────────┬───────────────┤
│  IPD                         │ Bed Occupancy │ OPD Volume     │ Emergency     │
│  RAD Diagnostic              │ donut +       │ grouped bars   │ acuity donut  │
│  Pharmacy                    │ legend        │ + legend       │ + flow stats  │
│  Insurance                   ├──────────────────────────────────┬────────────┤
│  Store                       │ Today's Operation Theatre        │ Critical   │
│  Sterilization               │ schedule table                   │ Alerts     │
│  Reports                     │                                   │ list       │
│  Billing                     ├─────────────────────────┬────────┴────────────┤
│                               │ Recent Admissions &     │ Patient Flow Funnel │
│ QUALITY & COMPLIANCE         │ Discharges              │                    │
│  NQAS / NABH                 ├─────────────────────────┴──────────┬─────────┤
│  Clinical Safety             │ Department Performance              │         │
│  Audit & Feedback            └──────────────────────────────────────┘         │
└───────────────────────────────┴────────────────────────────────────────────────┴────────┘
```

### 8.2 Dashboard header

The dashboard header has four bands:

**Band 1 — global shell.** Use the shell defined in §5. The screenshot pattern is search-first: the search control is wide enough for long patient queries and shows `Ctrl K` as the keyboard hint.

**Band 2 — context and welcome.** Left: current date and welcome message. Right: green `Live Data` state with `Last updated`, calendar/date context and a four-state range control: `Today / This Week / This Month / This Year`.

**Band 3 — KPI strip.** Six cards at 1536 px; five or six cards at 1920 px depending on configured metrics. At 1366 px use six narrower cards only when content remains readable; otherwise wrap to two rows.

**Band 4 — dashboard grid.** 12-column CSS grid. Default desktop spans:

| Region | Grid span |
|---|---:|
| Bed Occupancy | 4/12 |
| OPD Volume Trend | 4/12 |
| Emergency — Acuity & Flow | 4/12 |
| Operation Theatre Schedule | 8/12 |
| Critical Alerts | 4/12 |
| Admissions & Discharges | 6/12 |
| Patient Flow Funnel | 3/12 |
| Department Performance | 3/12 |

### 8.3 KPI card specification

Each KPI card follows the visual order visible in the reference:

```text
┌──────────────────────────────┐
│ [icon tile]  KPI label       │
│                              │
│ 26,710                       │
│ ↑ 12%                        │───╮
│ vs. 23,864 last month        │   └─ SVG sparkline
└──────────────────────────────┘
```

Rules:

- Card height: **124–136 px** at desktop.
- Icon tile: **40×40 px**, rounded 10 px, very soft contextual background.
- KPI value: 28–32 px, tabular numerals, 700 weight.
- Trend: green/red only when accompanied by arrow/text such as `↑ 12%`; do not rely on colour alone.
- Comparison period is always explicit: `vs. yesterday`, `vs. last month`, etc.
- Sparkline: 88–104 × 28 px inline SVG; no chart axis; provide accessible summary.
- Card action, when present, is icon-only only with an accessible name; otherwise the whole card can be clickable.

Recommended dashboard metrics are configured by role and tenant. The screenshot uses examples such as Total Patients, OPD Visits, Admitted Patients, Emergency Cases, Lab Tests and Pending Claims. The design system must not hard-code these values.

### 8.4 Bed Occupancy card

Use a donut with a large center value and a right-side legend.

```text
┌─────────────────────────────────────────┐
│ Bed Occupancy                 View ›    │
│                                         │
│        ◜██████████◝    Occupied   410  │
│       │    82%     │   Available   90   │
│       │ 410 / 500  │   Blocked     18   │
│        ◟██████████◞    Maintenance   2  │
└─────────────────────────────────────────┘
```

Use explicit labels for occupied/available/blocked/maintenance. The denominator must come from the configured hospital bed data; the dashboard does not redefine the Quality OS denominator.

### 8.5 OPD Volume Trend

The reference uses a grouped vertical bar chart with two series and seven daily categories. Implement as inline SVG.

- X-axis: day abbreviation + date.
- Y-axis: count with automatic tick spacing.
- Legend: Male / Female or configured breakdown.
- Bar width: 16–22 px at 1536 px with 8–12 px series gap.
- Hover/focus reveals exact value in a tooltip.
- Add a `This Week` range control and optional `All Departments` filter.
- Provide a data-table toggle below the chart for accessibility and print.

### 8.6 Emergency — Acuity & Flow

Use a donut for acuity distribution and three compact flow stats below it:

`Waiting | In Treatment | Discharged`

The acuity legend remains text-visible with category, count and percentage. Categories are represented with both colour and distinct marker shapes/patterns in print/greyscale.

### 8.7 Operation Theatre schedule

This is the largest table on the reference dashboard. Use eight columns maximum at 1536 px:

`Time | OT | Procedure | Patient | Surgeon | Status | [optional field]`

- 44 px row height for the dashboard preview.
- Time uses a pill-like soft background by status.
- Patient names are visible only to users with the required patient-access permission.
- Status uses text badges: `Ongoing`, `Up Next`, `Scheduled`.
- `View All` opens `/ot/schedule` in R5; the dashboard card is therefore a cross-release navigation surface and must not show an R5 route when OT is disabled. Use `Not enabled` configuration state.

### 8.8 Critical Alerts

Right-side alert panel is high priority. Match the reference hierarchy:

```text
Critical Alerts  [5]
────────────────────────────────────
● ICU Bed Availability Low       10:12 AM
  Only 4 beds available…
● High Risk Lab Result            09:48 AM
  Hb 6.8 g/dL…
● Pending Insurance Approval      09:20 AM
  12 PMJAY claims pending…
● Equipment Maintenance Due       08:55 AM
● Pharmacy Stock Alert            08:30 AM
```

Severity icon, heading, supporting text and timestamp are all required. Critical alerts cannot be colour-only. This panel is fed by the persisted notification engine; realtime delivery may use the authorised notification WebSocket. [P-RT-1, PLT-001]

### 8.9 Recent Admissions & Discharges

Use a compact table with an `Admissions / Discharges` segmented control. Recommended columns:

`Time | UHID | Patient Name | Age/Sex | Department | Type | Status`

Status must remain text-visible, e.g. `Admitted`, `Discharged`. Patient identity follows the same access rules as all patient lists.

### 8.10 Patient Flow Funnel

The reference uses a descending funnel with five stages: Registered → Seen by Doctor → Investigations → Admitted → Discharged. Build using stacked SVG trapezoids or polygon primitives, with a legend containing count and percentage.

Do not use CSS/SVG animation to imply flow direction. The funnel is a static analytical visual with accessible tabular values.

### 8.11 Department Performance

Use a compact table:

`Department | OPD | IPD | Bed Occupancy | Status`

Bed occupancy uses a mini progress bar plus the numeric percentage. Status is a text badge (`Normal`, `High`) and may use colour as secondary encoding.

### 8.12 Dashboard density and spacing

At 1536×1024, the dashboard should fit the following without page scrolling in the normal state: global header, greeting/context, six KPI cards, three top charts, OT schedule, critical alerts, recent admissions/discharges, patient-flow funnel and department performance.

**Design decision:** the dashboard uses compact enterprise density even though general application pages default to comfortable density, because the reference explicitly prioritises a single-screen operational overview.

### 8.13 Dashboard role variants

**Medical Superintendent / CEO:** use the reference composition with hospital flow, occupancy, alerts, OT, admissions, patient flow and department performance.

**Quality Manager:** replace revenue/operational emphasis with `Enabled indicators | Valid | Provisional | Exceptions | CAPA | Data quality | Period close`, while retaining the same shell, KPI card geometry and three-panel analytical grid.

**Tenant Administrator:** prioritise `Setup completion | Users | Facilities | Departments | Beds | ABHA/QR | Accreditation profile | System health`.

**Registration Clerk:** do not present executive analytics by default. Use a compact command-centred dashboard with `New Registration | Find Patient | Awaiting Verification | Today's Queue | Token Display`.

### 8.14 Dashboard interaction and refresh

- Dashboard operational values: TanStack Query; default `refetchInterval: 30s`.
- `Last updated` is always visible beside the live-data state.
- At 60–90 seconds old, switch the indicator to `Stale data` and offer `Refresh now`.
- Failure of refresh does not remove the last confirmed values; show a non-blocking error strip.
- Critical alert delivery may use Django Channels because it is part of the notification engine; persisted notifications remain the source of truth.
- Charts never require a charting library; all dashboard charts are inline SVG.

### 8.15 Screenshot alignment checklist

The implementation should visually reproduce the supplied reference before adding tenant-specific data. QA/design review should verify:

| Reference element | Implementation check |
|---|---|
| Dark navy sidebar | Full-height 240 px rail; grouped navigation; compact Lucide icons; active item uses blue emphasis and a clearly visible selected state. |
| Search-first header | Search field occupies the dominant header width and shows keyboard hint `Ctrl K`; facility selector, bell and user identity remain right-aligned. |
| Welcome/context row | Date, greeting, live-data state, last-updated time and date-range control align on one horizontal band at desktop widths. |
| Six KPI cards | Equal-width cards, consistent icon tiles, 28–32 px values, delta text and mini sparklines. |
| Three analytical cards | Bed Occupancy donut, OPD grouped bars and Emergency acuity donut share equal visual height. |
| OT schedule | 8-column maximum preview table with compact rows and text status badges. |
| Critical alerts | Right rail remains visually prominent; severity icon + title + supporting line + timestamp are all visible. |
| Lower row | Admissions/discharges table, funnel and department table align to a common baseline. |
| Card treatment | White surfaces, 1 px cool-grey border, 8 px radius, minimal shadow, 16–20 px internal padding. |
| Background | Cool near-white canvas with visible separation between cards without strong section blocks. |

**Implementation note:** sample values from the screenshot are illustrative. Use API data and tenant configuration; do not hard-code patient names, numbers, dates, departments or alerts from the reference image.

## 9. Quality OS visual language

### Indicator cards

```text
┌────────────────────────────────────────┐
│ Bed Occupancy Rate         NQAS-DH-001 │
│                                        │
│ 82.4 %                 ● Valid         │
│ Target 75–85 %         Oct 2026        │
│                                        │
│ ▁▂▃▅▆▇▆▅▇  Run chart                  │
│                                        │
│ View indicator →                       │
└────────────────────────────────────────┘
```

For non-percentage indicators:

```text
Average length of stay
6.4 days   ● Valid
```

For direct counts:

```text
Number of sterilization failures
3 cases   ● Valid
```

### Provenance panel

Every indicator detail page must provide a collapsible `Source & calculation` section containing:

- framework;
- edition;
- source document;
- source sheet/standard;
- source serial/page/locator;
- scope;
- source frequency;
- calculation mode;
- numerator/denominator or source operator;
- sampling guidance;
- definition version;
- import timestamp/hash where permitted.

The Quality OS source model requires provenance and historical definition versions. [QOS-002, QOS-007, QOS-008]

## 10. Navigation page designs

### Registration

Split view on desktop:

```text
┌──────────────────────────────┬──────────────────────────────────┐
│ Patient search               │ Registration                      │
│ [UHID/name/mobile ______]   │ Patient found/new                │
│                              │ Department [ OPD ▾ ]             │
│ Results                      │ Demographics                      │
│ ┌──────────────────────────┐ │ Scheme/category                  │
│ │ UHID Name Age Sex       │ │ ABHA status                       │
│ └──────────────────────────┘ │ [ Register & issue token ]       │
└──────────────────────────────┴──────────────────────────────────┘
```

The search field receives focus on entry. Duplicate warnings appear before the final save.

### OPD dashboard

Use a three-zone layout: queue, current patient context and consultation summary. Avoid tabbing the core patient history behind a modal.

### Doctor consultation

```text
┌──────────────┬────────────────────────────────────┬─────────────────────┐
│ Queue        │ Patient header                     │ Actions             │
│              │ UHID / name / age / sex / status   │ Complete encounter  │
│ Token 21     ├────────────────────────────────────┤ Print OP slip        │
│ Token 22     │ History | Problems | Medications   │                     │
│ Token 23     │ Allergies | Previous encounters   │                     │
│              ├────────────────────────────────────┤                     │
│              │ Structured notes                   │                     │
│              │ Diagnosis                           │                     │
│              │ Prescription                        │                     │
└──────────────┴────────────────────────────────────┴─────────────────────┘
```

### IPD bed board

Use a grid of `BedTile` components grouped by ward.

```text
Ward: Medicine A                         32 / 40 occupied

[01 OCCUPIED] [02 EMPTY] [03 CLEANING] [04 RESERVED]
[05 OCCUPIED] [06 OCCUPIED] [07 EMPTY]  [08 OCCUPIED]
```

The screen uses REST polling/refetch, not WebSockets. Display `Updated 12:41:08` and a stale state when data exceeds the configured freshness window. [PLT-003, P-RT-4]

### Discharge

The disposition control must be visible near the beginning of the form and cannot be skipped.

Options include: `Routine`, `LAMA`, `Absconded`, `Referred`, `Death`, and configured `Other`. [IPD-006]

Selecting a disposition reveals only the required contextual fields. The final button reads `Complete discharge`, not `Save`.

## 11. Tables and data-dense views

Use Shadcn `Table` with a reusable `DataTable` wrapper.

Rules:

- server-side pagination;
- 25/50/100 rows per page;
- sticky header;
- optional sticky first column for very wide tables;
- sortable columns only when supported by the API;
- filtering above the table, not hidden in a modal;
- row actions under a kebab menu only when more than two actions exist;
- numeric values right-aligned;
- status values use text + icon + semantic style;
- no zebra striping unless contrast testing shows a measurable benefit.

Quality catalogue columns:

`ID | Framework | Indicator | Scope | Type/Standard | Department/Specialty | Frequency | Calculation | Status | Enabled`

The filter bar must support framework, edition, indicator type/standard, department/specialty, frequency and calculation mode. [P-QOS-8]

## 12. Forms and controls

### Inputs

Default height: **40 px** desktop; **44 px** tablet/ward mode.

Required labels use `*` plus accessible required metadata.

Use helper text for domain-specific terms such as UHID, ABHA and LAMA.

### Buttons

Variants:

- `default`: primary teal action.
- `secondary`: neutral filled action.
- `outline`: secondary action.
- `ghost`: navigation/context action.
- `destructive`: irreversible action only.

Height: 40 px standard, 44 px for primary/touch actions.

### Dialogs

Use for confirmation, focused review or small configuration tasks. Never open a dialog on top of another dialog.

### Drawers

Use for contextual details such as audit trail, filters on tablet, patient history and evidence preview.

## 13. Notifications and realtime states

The application has a persisted notification centre. Django Channels is permitted only for realtime notifications and live ICU/ward vitals; all other operational views use REST polling/refetching. [Architecture §13; INT-012/013]

Notification icon states:

```text
○ No unread
● 3 unread
! Critical alert pending acknowledgement
```

Critical notifications must persist after reconnect because database persistence is the source of truth.

For polled screens show:

`Updated 12:41:08 • Refresh`  
`Refreshing…`  
`Stale • Last successful update 12:32:14`

## 14. Offline and unsynced visual language

Ward PWA screens can show locally queued entries.

```text
[UNSYNCED] Observation entered locally at 12:42
Waiting for server confirmation
```

Clinical orders must use stronger semantics:

```text
[NOT SAVED]
Order captured locally. Waiting for server confirmation.
Do not treat this order as active.
```

Never use a success toast for a clinical order before server confirmation. [UI-007, NFR-USE-003]

## 15. Charts

Only inline SVG is allowed.

### Run chart

- 16 px left/right internal plot margin.
- X axis = reporting periods.
- Y axis = source-defined unit/value.
- centre line = median or configured centre value.
- target = dashed line with text label.
- provisional points = outlined markers.
- locked points = filled markers plus lock icon in tooltip/text alternative.
- signal points = distinct marker shape, not only colour.

### Control chart

Display:

`LCL`, centre line, `UCL`, target where applicable, observations and signal markers.

Allowed source-appropriate methods: p, u, XmR or other method required by the indicator definition. [QOS-060]

### Donut

Only for categorical composition where a donut actually conveys the source data. A centre total is allowed. Values must also be available in an accessible data table.

### SVG accessibility

Every chart has:

- visible title;
- accessible text summary;
- data-table toggle;
- non-colour signal encoding;
- print-safe line/marker distinction.

## 16. Dark mode

Dark mode is class-driven through Tailwind semantic CSS variables. [Architecture §14.1]

Rules:

- never invert clinical imagery or uploaded evidence;
- use dark surfaces around `#111827` rather than pure black;
- retain readable status text and icons;
- do not use colour alone for warnings;
- lower decorative contrast, not informational contrast.

## 17. Responsive behavior

### 1366×768 desktop

Target baseline. Sidebar expanded, content max-width fluid, two- and three-column cards allowed.

### 1920×1080

Increase content breathing room but do not stretch line lengths indefinitely. Dashboard grid may expand from 4 to 6 cards per row.

### Tablet landscape

Collapse sidebar to icon rail. Inputs and major buttons 44 px high. Two-column layouts become one primary content column plus an optional side sheet.

### Tablet portrait

Use single-column workflows. Filters move into `Sheet`. Patient context remains sticky.

### Phones

Phone use is intentionally not a primary workstation target for the authenticated hospital application. Do not design dense clinical operations around phone-sized layouts. Patient-facing ABHA interactions occur in the ABDM app, outside this application.

### Kiosk

Full-screen route. No sidebar, no login prompt. Large token typography, high contrast, REST polling and automatic reconnect. [UI-003]

## 18. Printing

Print templates must be configurable.

### OP slip

Minimum content:

`Hospital name | Facility | UHID | Patient name | age/sex | department | visit date/time | token | registration/visit details | QR/barcode where configured`

### Receipt

`Hospital | receipt no. | patient/UHID | service lines | discounts/scheme/free status | amount | payment mode | timestamp | authorised issuer`

### Discharge summary

Use A4 portrait with clear patient identity header, admission/discharge information, diagnosis, treatment summary, disposition, follow-up and signature areas.

### Quality report

A4/landscape for tabular registers. Keep source reference and definition version visible for audit-oriented reports.

## 19. Product-specific composite components

| Component | Main props | Key states | Use |
|---|---|---|---|
| `PatientBanner` | patient, encounter, verificationState | verified/provisional/wrong-context | Clinical + billing + drill-through |
| `UhidBadge` | uhid, copyable | default/copied | All patient views |
| `AbhaStatusBadge` | status | linked/unlinked/pending/error | Registration |
| `TokenCard` | token, patient initials, state | waiting/called/completed | OPD |
| `BedTile` | bed, occupancy, cleanliness | occupied/empty/cleaning/reserved | IPD |
| `DataTable` | columns, query, pagination | loading/empty/error/read-only | Admin + Quality |
| `FilterBar` | fields, value, onChange | compact/expanded | Catalogue + reports |
| `StatusPill` | status | critical/warning/success/info | Everywhere |
| `UnsyncedIndicator` | syncState | queued/syncing/conflict | Ward PWA |
| `ProvisionalLockedBadge` | state | provisional/locked/superseded | Patient + Quality |
| `IndicatorCard` | definition, value, unit, trend | valid/provisional/exception | Quality OS |
| `RunChart` | series, target, centreLine | empty/loading/loaded | Quality OS |
| `ControlChart` | series, ucl/lcl, target, signals | empty/loading/loaded | Quality OS |
| `SparkLine` | series | empty/loading/loaded | KPI cards |
| `Donut` | segments | empty/loaded | Dashboard |
| `BarChart` | bars, axis | empty/loading/loaded | Dashboard + Quality |
| `CapaTimeline` | events | active/closed/reopened | CAPA |
| `EvidenceUploader` | files, policy | idle/uploading/failed/complete | CAPA/audits |
| `AuditTrailDrawer` | events | loading/empty/loaded | Patient + admin |
| `EmptyState` | title, explanation, action | empty | All list pages |
| `ErrorRecovery` | error, retry | retrying/failed | All data screens |

Every composite must use the Shadcn primitives and Lucide icons already established in the repository. Components not in the current registry should be added through the normal Shadcn workflow and marked as `to add` before implementation.

## 20. Iconography

Use Lucide React only.

Recommended semantics:

| Purpose | Icon |
|---|---|
| Search | `Search` |
| Notifications | `Bell` |
| Settings | `Settings` |
| Patient | `UserRound` |
| Add | `Plus` |
| Edit | `Pencil` |
| Delete | `Trash2` |
| More | `MoreHorizontal` |
| Lock | `Lock` |
| Warning | `TriangleAlert` |
| Critical | `CircleAlert` |
| Success | `CircleCheck` |
| Print | `Printer` |
| Download | `Download` |
| Refresh | `RefreshCw` |
| Audit | `History` |
| External | `ExternalLink` |

Every icon-only button requires an accessible name.

## 21. Dashboard role variants

The visual baseline for all role variants is the screenshot-informed dashboard grid in §8.

### Medical Superintendent / CEO

Show:

`Occupancy | OPD volume | Admissions | Discharges | Mortality where permitted | Revenue where permitted | Quality summary | Open CAPA`

### Quality Manager

Show:

`Enabled indicators | Valid/provisional | Data-quality exceptions | Alerts | CAPA | Period close | Trend exceptions`

### Tenant Administrator

Show:

`Setup completeness | Users | Facilities | Departments | Beds | ABDM/QR status | Accreditation profile | System notifications`

### Registration Clerk

Do not show executive analytics by default. Landing page should prioritise:

`New registration | Find patient | Awaiting verification | Today's queue | Token display`

## 22. Government and private visual configuration

The application does not fork its visual codebase for government/private hospitals. Tenant configuration changes:

| Area | Government | Private |
|---|---|---|
| Registration | Scan and Share + counter | Scan and Share/counter |
| Billing | Free/scheme-covered states prominent | Tariff/payment states prominent |
| Quality | NQAS default | NABH default |
| Reporting | Government-oriented configured exports | Internal quality/assessor outputs |

The same components and layout system are reused. Only labels, fields, enabled modules, status options and default navigation change with tenant configuration. [PRD §8]

## 23. Accessibility baseline

Core visual requirements:

- WCAG 2.1 AA for core workflows.
- Keyboard focus visible with `--ring`.
- 44×44 px minimum touch targets on tablet.
- No colour-only status communication.
- Labels always associated with inputs.
- Icon-only controls always have accessible names.
- 200% text zoom must preserve usable layout for core workflows.
- `prefers-reduced-motion` disables non-essential transitions.
- Data charts have a text/data-table alternative.

The three highest-risk accessibility workflows are returning-patient registration, discharge and Quality OS monthly close.

## 24. Motion

Motion should communicate state, not decorate the interface.

- hover/focus: 80–120 ms;
- panel open/close: 160–200 ms;
- page skeleton transitions: none or <150 ms;
- no looping motion except kiosk reconnect indicator and live-vitals signal where clinically useful.

Reduced-motion mode removes movement and retains state changes through static styling.

## 25. Frontend implementation rules

Folder convention:

```text
src/
  components/ui/          # Shadcn-owned primitives
  components/hmis/        # Product composites
  modules/
    auth/
    dashboard/
    patient_registry/
    opd/
    ipd/
    emr/
    billing/
    quality_os/
    admin/
  styles/
    globals.css
```

Use:

- TanStack Query for server state and cache/refetch behaviour.
- React Hook Form + Zod for forms.
- Zustand for active patient tabs and UI preferences.
- Tailwind CSS v4 utility classes with semantic CSS variables.
- Lucide React for icons.
- Inline SVG for charts.

Route-level module code splitting is mandatory. Do not add SSR.

## 26. Non-negotiable UX rules

1. Never display another tenant's data.
2. Never show a clinical order as saved before server confirmation.
3. Never hide patient identity context during a clinical workflow.
4. Never make discharge disposition optional.
5. Never make merge or period-lock actions single-click operations.
6. Never use WebSockets for ordinary operational boards; use REST polling/refetch.
7. Never represent every Quality OS indicator as a percentage.
8. Never use colour as the only meaning of a status.
9. Never place a modal on top of a modal.
10. Never silently overwrite locked quality history.

## 26A. Supplied dashboard reference

The visual dashboard reference supplied with this project is a **1536×1024 desktop composition**. It is incorporated into §5 (application shell), §8 (dashboard grid and cards), §21 (role variants), and §22 (government/private visual configuration). When implementing the page, match the reference hierarchy and density first, then apply tenant configuration and live data. Sample names, dates, metrics and patient values in the image are illustrative data and must not be hard-coded.

## 27. Source alignment

This design file is derived from:

- `SaaS HMIS PRD v0.5.md`
- `SaaS HMIS SRS v0.5.md`
- `SaaS HMIS Architecture v0.6.md`
- `SaaS HMIS Quality OS Indicator Specification v0.2.md`
- `SaaS HMIS Quality OS Indicator Catalog v0.2.json`

The architecture fixes Shadcn UI, Tailwind CSS v4, semantic CSS variables, Lucide icons, inline SVG charts, TanStack Query, React Hook Form + Zod, Zustand and the constrained Django Channels realtime model. [Architecture §4, §13, §14.1]

The Quality OS source baseline is 406 indicators: 356 NQAS and 50 NABH. The NQAS set consists of 30 KPI-sheet indicators plus 326 indicators across 18 department/service sheets; the NABH set consists of 32 organisational and 18 department-specific KPIs. [Indicator Specification §1]

## 28. Design decisions requiring future confirmation

These are intentional defaults, not source requirements:

| Decision | Default |
|---|---|
| Supporting brand colours | Semantic palette in §2.3 |
| Font | Inter/system stack with Devanagari fallback |
| Dashboard background | `#f8fafc` |
| Card radius | 8 px |
| Login card width | 420 px |
| Standard control height | 40 px |
| Tablet control height | 44 px |
| Sidebar width | 240 px |
| Header height | 64 px |
| Data table page sizes | 25/50/100 |
| Default dashboard density | Comfortable; compact in registration/billing/data-heavy screens |
| Phone support | Not a primary authenticated workstation target |

These decisions can be changed without altering the architectural constraints.
