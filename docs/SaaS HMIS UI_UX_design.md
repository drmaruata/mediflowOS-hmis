# SaaS HMIS — UI/UX Design Specification

**Version:** 0.1 (draft)  
**Date:** 2 Oct 2026  
**Status:** For review  
**Derived from:** `SaaS HMIS PRD v0.5.md`, `SaaS HMIS SRS v0.5.md`, `SaaS HMIS Architecture v0.6.md`, `SaaS HMIS Quality OS Indicator Specification v0.2.md`, `SaaS HMIS Quality OS Indicator Catalog v0.2.json`

### Table of contents

1. [Purpose, scope and how to use this document](#1-purpose-scope-and-how-to-use-this-document)
2. [Design principles as testable rules](#2-design-principles-as-testable-rules)
3. [Users and contexts of use](#3-users-and-contexts-of-use)
4. [Information architecture](#4-information-architecture)
5. [Design system, built on Shadcn + Tailwind v4](#5-design-system-built-on-shadcn--tailwind-v4)
6. [Cross-cutting interaction patterns](#6-cross-cutting-interaction-patterns)
7. [Screen specifications for R1 (Foundation)](#7-screen-specifications-for-r1-foundation)
8. [Screen specifications for R2 (Core clinical)](#8-screen-specifications-for-r2-core-clinical)
9. [Screen specifications for R3 (Quality OS v1)](#9-screen-specifications-for-r3-quality-os-v1)
10. [Lighter coverage for R4-R7](#10-lighter-coverage-for-r4-r7)
11. [Government vs private configuration in the UI](#11-government-vs-private-configuration-in-the-ui)
12. [Accessibility and inclusive design](#12-accessibility-and-inclusive-design)
13. [Localisation and content design](#13-localisation-and-content-design)
14. [Responsive and device behaviour](#14-responsive-and-device-behaviour)
15. [Performance and perceived-performance budget for the UI](#15-performance-and-perceived-performance-budget-for-the-ui)
16. [Open questions, assumptions and risks](#16-open-questions-assumptions-and-risks)
17. [Traceability matrix](#17-traceability-matrix)
18. [Appendix: usability test plan and screen inventory](#18-appendix-usability-test-plan-and-screen-inventory)

### Change log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2 Oct 2026 | Initial end-to-end R1-R3 contract; R4-R7 pattern coverage; direct validation of catalogue data shape. |

## 1. Purpose, scope and how to use this document

This document is the design contract between product, frontend engineering and QA. It is derived from the five supplied project artifacts. The precedence order is **Architecture v0.6 > SRS v0.5 > PRD v0.5 > Quality OS Indicator Specification v0.2 > Indicator Catalog v0.2 JSON**.

R1-R3 are the MVP and receive full screen-level detail. R4-R7 receive lighter coverage. Architecture constraints are treated as fixed decisions, not alternatives: React + TypeScript Vite SPA; Shadcn UI + Tailwind CSS v4 + Radix; `lucide-react`; inline SVG charts; TanStack Query; React Hook Form + Zod; Zustand; Django/DRF; Celery/Celery Beat; Django Channels only for persisted realtime notifications and live ICU/ward vitals; REST polling for other operational screens; short-lived PWA offline queue; Indian-region PHI storage; configurable print templates. [Architecture v0.6 §4, §13, §14.1; SRS UI-001-007, INT-011-014]

The Quality OS baseline is **406 definitions: 356 NQAS District Hospital indicators and 50 NABH 6th Edition KPIs**. NQAS contains 30 hospital-wide KPI rows and 326 rows across 18 department/service sheets; NABH contains 32 organisational and 18 department-specific KPIs. [PRD §5, §8; Indicator Specification §1, §5.2]

Use this document as follows: designers use §§2-6 as the interaction system; engineers use §§7-10 as route/component/API contracts; QA derives executable tests from acceptance criteria and cross-cutting rules. Any deviation must reference the route and requirement IDs.

## 2. Design principles as testable rules

### 2.1 Capture once, use everywhere

**Rule.** Structured data entered during normal workflow is reused by billing, EMR and Quality OS; users are not asked to re-key the same fact. [PRD §1.4; QOS-020/021]

**Example.** IPD discharge records `LAMA` once; downstream LAMA/discharge-related indicators consume that event.

**How QA checks it.** Create a discharge with `LAMA`; verify EMR and Quality OS drill-through show the same admission/event IDs and disposition, with no duplicate quality form.

### 2.2 Quality by design

**Rule.** Mandatory source fields are visible, marked required and validated before submit. Conditional fields appear immediately when their controlling value changes. [IPD-006/007; QOS-021]

**Example.** `Disposition` is required; selecting `death` reveals cause-of-death; selecting `referred` reveals referral destination.

**How QA checks it.** Submit with missing disposition; save is blocked and focus moves to disposition.

### 2.3 India-first

**Rule.** Use Indian date/number/currency conventions; make ABHA, UHID, OP slip and government scheme categories first-class; keep state/government exports configuration-driven. [REG; ABD; P-BIL-4; NFR-INT-002]

**How QA checks it.** Verify `02/10/2026`, `₹1,500.00`, ABHA status, category labels and translated strings at 200% zoom.

### 2.4 Usable on a busy ward

**Rule.** Keyboard-first workflows, deterministic focus, 44×44 px touch targets on tablet, no modal-on-modal, compact density for data-entry-heavy pages. [UI-001/002; NFR-USE-001]

**Interaction budgets.** Returning-patient registration ≤30 s keyboard interaction; patient search→open ≤6 activation steps; bed allocation ≤5; discharge completion ≤6 when valid; common list refresh is non-blocking.

**How QA checks it.** Run keyboard-only tests at 1366×768 and tablet landscape and count activations.

### 2.5 Safe by default

**Rule.** Patient identity is persistent; destructive/high-risk actions require explicit context and confirmation; break-glass requires reason and audit; clinical orders are never shown as saved before server confirmation. [P-ADM-4; AUD-001-003; UI-007]

**How QA checks it.** Attempt merge, discharge, bed allocation, payment and period lock under wrong/stale context; each action must block safely.

### 2.6 Failure visibility

**Rule.** `Saving`, `Saved on server`, `Unsynced`, `Failed`, `Read-only`, `Provisional`, `Locked`, `Stale` and `Reconnecting` are textual states, not colour-only states.

**How QA checks it.** Disconnect during an eligible ward draft; verify unsynced state; disconnect during a clinical order; verify the UI never says Saved.

## 3. Users and contexts of use

| Persona | Device/location | Interruptions/connectivity | Language | Top 3 tasks | Failure looks like |
|---|---|---|---|---|---|
| Registration clerk | Desktop, OPD counter | Queue pressure; brief outages | English; patient slips later localised | Search/register; token; slip | Duplicate/wrong patient; queue stall |
| Self-registering patient | Own phone, facility | Mobile signal; ABDM app controls UI | Configured patient language | Scan QR; share profile; receive token | No match/token unclear |
| OPD doctor | Desktop, consultation room | Interruptions/shared workstation | English | Queue; history; notes/prescription | Wrong patient/order/lost draft |
| Nurse/ward in-charge | Desktop/tablet, ward | Rounds; Wi-Fi variability | English/local later | Admit; chart/handover; discharge | Wrong bed/patient; unsynced data |
| Lab technician | Desktop, lab | Batch work; analyzer/network issues | English | Receive; collect; result/critical flag | Sample/result mismatch |
| Radiologist/technician | Imaging workstation | Throughput and PACS dependency | English | Worklist; report; image viewer | Wrong study/patient |
| Pharmacist | Desktop, pharmacy | Long queues/stock pressure | English | Dispense; stock; stock-out | Wrong drug/patient/quantity |
| Billing/TPA executive | Desktop, billing | Payment/network interruptions | English | Charges; payment; receipt | Wrong tariff/payment |
| MS/CEO | Desktop | Meetings/intermittent viewing | English | Occupancy; flow; quality/revenue | Misread/stale KPI |
| Quality manager | Desktop | Month-end density; many tabs | English | Indicators; DQ; CAPA | Unsupported/unreproducible value |
| Tenant administrator | Desktop | Setup/change windows | English | Users; config; quality profile | Destructive/cross-context change |
| Platform administrator | Desktop | Multi-tenant support | English | Onboard; catalogue; audit | Cross-tenant leakage/bad import |
| Kiosk viewer | Wall display | Network drop; no operator | Patient-facing configured language | Show token; reconnect; last update | Frozen/wrong token/login prompt |

## 4. Information architecture

### 4.1 Site map and role-based navigation

Departments, wards, beds and service units are tenant configuration, not application modules. OPD/IPD are generic engines driven by this structure. [Architecture §3, §6.1]

| Role | Visible navigation | R1 | R2 | R3 |
|---|---|---|---|---|
| Registration clerk | Patients, Registration, Notifications | Enabled | Enabled | Enabled |
| Doctor | Patients, OPD, IPD, EMR, Notifications | Basic | Enabled | Read-only Quality links where permitted |
| Nurse | Patients, IPD, Notifications | Basic | Enabled | Source links where permitted |
| Billing | Patients, Billing, Notifications | Basic | Enabled | — |
| Quality manager | Quality, Notifications, permitted patient views | — | — | Enabled |
| Tenant admin | Administration, Quality profile | Enabled | Enabled | Enabled |
| Platform admin | Platform, Tenants, Catalogue governance, Audit | Enabled | Enabled | Enabled |
| Kiosk | Dedicated kiosk route | Enabled | Enabled | Enabled |

A future-release module is hidden from clinical navigation. `Not enabled in this release` is shown only in administration/configuration surfaces.

### 4.2 Global shell

Top bar: facility logo/name, tenant badge, facility selector, department selector when relevant, global patient search, notification bell, user menu.

Patient context is held in Zustand. Each active tab shows `UHID · short name · age/sex` plus dirty/unsynced marker. Patient tabs persist across module navigation and are cleared on sign-out/context reset.

`Ctrl+K` opens the patient Command palette. Search supports UHID, name, mobile, ABHA number/address, approximate age/year of birth. Search results always show identity status before action. [REG-002]

### 4.3 URL and deep-link conventions

Routes are noun-first and lower-kebab. Module ownership mirrors `src/modules/<bounded_context>/`. Examples: `/patients`, `/patients/:uhid`, `/opd`, `/opd/consultation/:encounterId`, `/ipd/bed-board`, `/quality/indicators/:id`.

Deep links must restore tenant/facility context and re-authorise before fetching protected data. A stale/forbidden deep link lands on the nearest safe parent route with an explanatory message.

## 5. Design system, built on Shadcn + Tailwind v4

### 5.1 Colour tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `--background` | `0 0% 100%` | `222 22% 10%` | App background |
| `--foreground` | `222 47% 11%` | `210 40% 98%` | Text |
| `--card` | `0 0% 100%` | `222 22% 13%` | Panels |
| `--muted` | `210 40% 96%` | `217 19% 19%` | Secondary surface |
| `--muted-foreground` | `215 16% 35%` | `215 20% 72%` | Secondary text |
| `--primary` | `174 83% 25%` | `174 65% 42%` | Primary / focus |
| `--primary-foreground` | `0 0% 100%` | `0 0% 100%` | Primary button text |
| `--critical` | `0 74% 42%` | `0 74% 42%` | Critical |
| `--warning` | `36 92% 33%` | `36 92% 33%` | Warning |
| `--success` | `142 72% 29%` | `142 72% 29%` | Success |
| `--info` | `224 76% 48%` | `224 76% 48%` | Info |
| `--unsynced` | `262 83% 58%` | `262 83% 58%` | Offline/queued |
| `--provisional` | `220 9% 46%` | `220 9% 46%` | Provisional |
| `--locked` | `215 25% 27%` | `215 25% 27%` | Locked |
| `--border` | `214 20% 86%` | `217 18% 28%` | Borders |
| `--ring` | `174 83% 25%` | `174 65% 42%` | Focus |

All tokens are HSL triplets consumed through `hsl(var(--token))`. Primary is fixed by Architecture v0.6 to `#0f766e`.

### 5.2 Contrast checks

WCAG 2.1 AA target: normal text ≥4.5:1, large text ≥3:1, non-text boundaries/focus ≥3:1. The approved semantic foreground/background pairs are:

| Pair | Foreground | Background | Contrast ratio |
|---|---|---|---:|
| Primary | `#ffffff` | `#0f766e` | 5.47:1 |
| Critical | `#ffffff` | `#b91c1c` | 6.47:1 |
| Warning | `#ffffff` | `#a16207` | 4.92:1 |
| Success | `#ffffff` | `#15803d` | 5.02:1 |
| Info | `#ffffff` | `#1d4ed8` | 6.70:1 |
| Unsynced | `#ffffff` | `#7c3aed` | 5.70:1 |
| Provisional | `#ffffff` | `#6b7280` | 4.83:1 |
| Locked | `#ffffff` | `#334155` | 10.35:1 |
| Primary text | `#0f172a` | `#ffffff` | 17.85:1 |
| Secondary text | `#475569` | `#ffffff` | 7.58:1 |
| Dark primary text | `#f8fafc` | `#0f172a` | 17.06:1 |

These pairings are used in both themes for semantic status fills; surface/background tokens change by theme. CI must calculate the actual shipped CSS token contrast in both themes and fail on any normal-text pair below 4.5:1.

### 5.3 Typography, spacing, density and motion

| Token | Size/line-height | Weight |
|---|---|---|
| Display | 32/40 | 600 |
| H1 | 24/32 | 600 |
| H2 | 20/28 | 600 |
| H3 | 16/24 | 600 |
| Body | 14/20 | 400 |
| Body strong | 14/20 | 600 |
| Small | 12/16 | 400 |
| Micro | 11/14 | 500 |

Font stack: `Inter, Noto Sans Devanagari, system-ui, sans-serif`; other scripts use system fallback. Spacing: 4/8/12/16/20/24/32/40/48 px. Radius: 4 px controls, 8 px cards, 12 px dialogs. Motion: 120/160/220 ms; reduced-motion removes non-essential transitions and SVG animation.

Comfortable controls are ~40 px high. Compact controls are 32–36 px on dense desktop screens while tablet hit areas stay ≥44 px.

### 5.4 Component inventory

| Component | Source | Required states/variants | Product customisation |
|---|---|---|---|
| Button | Shadcn | default/secondary/outline/destructive/ghost/loading/disabled | 40/36 px sizes; aria-label on icon-only |
| Card | Shadcn | default/interactive/critical/warning | Semantic border |
| Badge | Shadcn | neutral/success/warning/critical/info/provisional/locked | Text always visible |
| Input | Shadcn | default/invalid/read-only/disabled | Keyboard-first |
| Dialog | Shadcn/Radix | confirm/form/safety | Single-layer |
| Tabs | Shadcn/Radix | patient/context/detail | Arrow navigation |
| Tooltip | Shadcn/Radix | hint | Never sole source for required text |
| Toast | Shadcn | success/info/warning/critical | Critical persists to acknowledgement |
| ScrollArea | Shadcn | vertical/horizontal | Touch affordance |
| Data Table | Shadcn Table + local composite | paging/sort/select/read-only | Server-side |
| Form | Shadcn + RHF | dirty/validating/error | Zod bound |
| Sheet | Shadcn | filter/detail | Tablet-friendly |
| Command | Shadcn/Radix | patient search/quick actions | `Ctrl+K` |
| Popover/Calendar | Shadcn/Radix | filter/date | Indian date display |
| Checkbox/Radio/Switch | Shadcn/Radix | states | Explicit labels |
| Textarea | Shadcn | normal/error/read-only | Clinical free text |
| Alert | Shadcn | info/warning/critical | Text + icon |
| Skeleton | Shadcn pattern | card/row/page | Stable geometry |
| Breadcrumb/Pagination/Accordion | Shadcn | route/paging/detail | Accessible semantics |
| **To add** | Local composite | See §5.5 | Product-owned |

### 5.5 Product-specific composites

| Component | Props / contract | Required states | Accessibility | Used in |
|---|---|---|---|---|
| `PatientBanner` | `patient`, `encounter?`, `verificationStatus`, `readOnly`, `onOpenProfile` | verified, provisional, unsynced, safety | First landmark in clinical content; name/UHID/age-sex exposed as one labelled group | OPD, IPD, EMR, billing, Quality drill-through |
| `UhidBadge` | `uhid`, `copyable`, `size` | default, copied, unavailable | Copy button has `aria-label="Copy UHID"`; copied state announced | Patient registry and all patient-context surfaces |
| `AbhaStatusBadge` | `status` | verified, linked, not-linked, pending | Text status plus icon; never colour-only | Patient profile, registration, QR verification |
| `TokenCard` | `token`, `department`, `status`, `calledAt` | queued, called, completed, cancelled | Status text and semantic heading; kiosk avoids protected identity | Registration and kiosk |
| `BedTile` | `bed`, `patient?`, `status`, `functional` | available, occupied, reserved, non-functional, blocked | Bed state announced from visible text; patient data omitted where kiosk/displayed publicly | Bed board, admission, ward administration |
| `DataTable` | `columns`, `queryKey`, `rowKey`, `serverPaging`, `filters` | loading, empty, error, partial, read-only | Header associations; row actions keyboard reachable; pagination labelled | Registry, admin, billing, Quality OS |
| `FilterBar` | `filters`, `onApply`, `onClear` | clean, dirty, applied, loading | Every filter labelled; keyboard submit and reset | Quality catalogue, alerts, CAPA, admin tables |
| `StatusPill` | `status`, `label`, `severity` | success, warning, critical, info, unsynced, provisional, locked | Visible status text plus icon/marker | Cross-product |
| `UnsyncedIndicator` | `count`, `oldestAt`, `onOpenQueue` | queued, syncing, conflict, failed | Includes explicit text `Unsynced`; queue action keyboard reachable | Ward/PWA workflows |
| `ProvisionalLockedBadge` | `state`, `reason` | provisional, locked, superseded, not-applicable | State and reason available to AT; no status by colour alone | Patient identity and Quality OS |
| `IndicatorCard` | `definition`, `value`, `unit`, `status`, `trend`, `period` | draft, provisional, locked, superseded, not-applicable, missing | Unit and value announced together; source status is text | Quality home/detail |
| `RunChart` | `points`, `centreLine`, `target`, `periodLabels`, `status` | loading, plotted, insufficient-data, provisional, locked | Text summary + table toggle; native unit on axis | Quality indicator detail |
| `ControlChart` | `points`, `centreLine`, `UCL`, `LCL`, `ruleSignals` | plotted, insufficient-data, signal, provisional, locked | Signal explained in adjacent text; table toggle | Quality indicator detail |
| `SparkLine` | `points`, `direction`, `label` | flat, improving, worsening, insufficient-data | Adjacent text gives direction/value; not relied on alone | Quality cards |
| `Donut` | `segments`, `total`, `labels` | normal, empty, loading | Central total plus legend and table alternative | Quality home |
| `BarChart` | `categories`, `values`, `benchmark` | normal, empty, loading | Category labels + table alternative; patterns distinguish benchmark | Quality home/detail |
| `CapaTimeline` | `events`, `currentState` | raised, RCA, action plan, implementation, verification, closed, reopened | Ordered list semantics mirror visual timeline | CAPA detail |
| `EvidenceUploader` | `acceptedTypes`, `maxSize`, `purpose` | idle, uploading, uploaded, failed, rejected | File input labelled; progress announced; errors adjacent | Sampling, CAPA, audit |
| `AuditTrailDrawer` | `subject`, `events`, `permissions` | loading, populated, empty, restricted | Drawer has labelled title and deterministic focus return | Patient access, admin, Quality evidence |
| `EmptyState` | `title`, `explanation`, `action?` | no-data, filtered-empty, not-enabled | Heading + explanation + labelled action | All data-bearing screens |
| `ErrorRecovery` | `errorCode`, `message`, `retry`, `supportRef?` | retryable, blocked, offline | Error summary is programmatically associated; Retry is focusable | All data-bearing screens |

Design decision: all composites are product-owned components built from the approved Shadcn/Radix primitives. Components not already in `src/components/ui/` are marked **to add** and must be added through the Shadcn CLI where an equivalent source component exists.

### 5.6 Inline SVG chart specification

No chart library. All charts are `<svg>` primitives. Minimum chart height 220 px; Quality OS detail charts 280–360 px. Plot has 12 px horizontal padding, 28 px top padding, 36 px x-axis label area.

Run chart: x = source frequency periods; y = native source unit; centre line = source-defined median/centre; target dashed; provisional hollow marker; locked filled marker; missing data is a gap plus table row.

Control chart: centre line + UCL/LCL + signal markers; use p-chart, u-chart or XmR only when the indicator semantics support the method. Do not choose a control-chart family solely from the display unit.

Colour-independent encoding: target = dashed line; centre = solid; limits = dotted; signal = triangle/cross; provisional = hollow; locked = filled; multiple series = differing dash/marker patterns. Every chart has a visible text summary and a `View data table` control.

## 6. Cross-cutting interaction patterns

### 6.1 Forms and validation

RHF + Zod. Required labels show `*` and `(required)` for assistive technology. Blur validation for identity/search; immediate validation for small enumerations; submit validation for cross-field rules. First invalid field receives focus. Server errors map to field/form scope using OpenAPI error codes.

Autosave is for non-clinical drafts only. Clinical actions may show draft/saving, but never automatic final submission. Dirty navigation guard applies to unsaved forms.

### 6.2 Search, duplicate warning and wrong-patient prevention

Search by UHID/name/mobile/ABHA/approximate age. Duplicate warning precedes new-record creation and lists identity confidence. Merge uses side-by-side records, explicit primary selection, typed `MERGE`, reason, server mutation and audit record. PatientBanner and UHID repeat in write areas.

### 6.3 Keyboard model

Global: `Ctrl+K` patient search, `Alt+N` notifications, `Alt+H` home, `Esc` close transient surface, `?` shortcut help.

Registration: `F2` search, `F4` new, `Alt+D` department, `Alt+T` token, `Ctrl+Enter` save.

OPD: `J/K` queue, `Alt+H` history, `Alt+P` prescription, `Ctrl+S` draft, `Ctrl+Enter` complete.

IPD: `Alt+B` bed board, `Alt+D` discharge, `Alt+T` transfer.

Quality: `/` filters, `G` indicator, `Alt+C` CAPA, `Ctrl+Shift+L` period-close panel.

### 6.4 Loading/empty/error/offline/degraded

Never display fake clinical values while loading. Use geometry-matched Skeleton. Empty states state why no data exists and what the next action is. Errors differentiate retryable vs blocked states. Partial data retains the last successful timestamp. Read-only is visible but retains data. Locked periods are visible and immutable.

### 6.5 Offline and conflict wording

Eligible ward drafts follow `Queued locally → Syncing → Saved on server`. Conflicts become `Needs review`. Exact wording: `Unsynced — saved on this device, not yet confirmed by the hospital server.` / `This entry changed on the server. Review the latest version before sending your local change.` / `Not synced. Your entry is still on this device for retry until the queue retention limit.` [UI-007, NFR-USE-003]

### 6.6 Polling vs WebSocket

Token kiosk: poll 3 s; bed board: 5 s; emergency board: 5 s; queues: 10 s; ordinary operational lists: 30 s. Show `Updated HH:MM:SS`; if last success exceeds 3× interval show `Stale`. No operational screen uses a WebSocket.

Only notification centre and R5 live-vitals use Django Channels. On WebSocket loss show `Reconnecting…`; for live vitals, TanStack Query continues REST refetch at the defined 5 s fallback interval. Persisted database state remains authoritative. [INT-012/013; PLT-001/002/003]

### 6.7 Notifications

Taxonomy: critical clinical, safety/security, data quality, workflow, system/integration, information. Critical items persist until authorised acknowledgement; acknowledgement stores actor/time. Reconnect reloads persisted state before applying realtime deltas. [P-RT-1; PLT-001]

### 6.8 Permissions, break-glass and audit

Hidden = access existence itself would disclose protected information. Disabled = action exists but state prevents it; show reason. Read-only = data visible, write permission absent. Break-glass requires reason and acknowledgement, shows `Break-glass active`, and exposes audit access. [P-ADM-3/4; AUD-001-003]

### 6.9 Destructive actions

Confirm only irreversible/high-risk actions: merge, revoke/regenerate QR, irreversible draft deletion if supported, period lock, CAPA reopen. Clinical records use versioned amendments rather than destructive delete. [NFR-REL-001]

### 6.10 Printing/export

OP slip: facility + UHID + patient + department + visit + token + configured ABHA/status and category/fee. Receipt: invoice + payment + amount/mode/time. Discharge: identity + admission/discharge + diagnoses/procedures/course + disposition + referrals + cause of death where applicable. QR poster: facility/intake point + large QR + instruction. Quality reports: framework + period + indicator register + provenance + exceptions + CAPA. [UI-006]

## 7. Screen specifications for R1 (Foundation)

R1 covers tenancy, identity, patient registry, audit, ABDM Scan and Share and notifications. The screen contracts below are intentionally operational rather than marketing-oriented.



### Sign-in  (route: `/auth/sign-in`, module: `src/modules/auth`, release: R1)
- **Purpose and persona:** Authenticate a staff user. Personas: all authenticated personas except kiosk. Trace: `UI-001`, `UI-002`, `INT-001`, `INT-011`.
- **Entry points and exits:** Direct URL/invite/auth redirect; exits to MFA, tenant selection or safe error state.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────┐
│ Hospital HMIS                                                Help │
├────────────────────────────────────────────────────────────────────┤
│                         Sign in                                    │
│ Username/email [____________________________]                     │
│ Password      [____________________________]                     │
│ [ Sign in ]                 [ Continue with SSO ]                  │
└────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Single column; primary CTA remains visible without scroll.
- **Components:** Card, Label, Input, Button, Alert.
- **Data and API:** POST `/auth/login`; no patient data; no realtime.
- **Fields and validation:**
| Label | Control | Required | Zod rule | Helper/error text |
|---|---|---|---|---|
| Username/email | Input | yes | `z.string().min(2)` | Enter your work username/email. |
| Password | Password | yes | `z.string().min(8)` | Password is required. |
- **States:** Loading, invalid credentials, locked account, network error.
- **Interactions and keyboard:** Username autofocus; Tab follows form; Enter submits.
- **Accessibility and localisation notes:** All controls labelled; errors associated with inputs; strings externalised.
- **Acceptance criteria:**
  - Given valid credentials; When Sign in is activated; Then the session is created and the user enters MFA or tenant context.
  - Given invalid credentials; When Sign in is activated; Then an inline error appears without revealing security details.
  - Given network failure; When submission occurs; Then retry is offered and no false success state appears.

### MFA  (route: `/auth/mfa`, module: `src/modules/auth`, release: R1)
- **Purpose and persona:** Complete configured MFA. Personas: privileged users. Trace: `TEN-006`.
- **Entry points and exits:** Post-authentication challenge; exits to authenticated shell or sign-in.
- **Layout:**
```text
┌──────────────────────────────────────────────┐
│ Verify identity                              │
│ Code [ _ _ _ _ _ _ ]                         │
│ [ Verify ]  Resend in 00:28                  │
└──────────────────────────────────────────────┘
```
Tablet/variant notes: Centered card.
- **Components:** Card, Input, Button, Alert.
- **Data and API:** POST `/auth/mfa/verify`; no polling.
- **Fields and validation:** `Code | OTP Input | yes | /^\\d{6}$/ | Enter the 6-digit code.`
- **States:** Active, invalid, expired, locked, offline.
- **Interactions and keyboard:** OTP autofocus; six-digit paste; Enter verifies.
- **Accessibility and localisation notes:** `autocomplete=one-time-code`; timer is not the sole status.
- **Acceptance criteria:**
  - Given a valid code; When Verify is activated; Then authentication completes.
  - Given an expired challenge; When Verify is activated; Then resend is offered and no session is created.
  - Given an invalid code; When Verify is activated; Then focus returns to the code field and error is announced.

### SSO entry  (route: `/auth/sso`, module: `src/modules/auth`, release: R1)
- **Purpose and persona:** Start OIDC/SAML sign-in. Personas: group/admin users. Trace: `P-ADM-2`, `INT-009`.
- **Entry points and exits:** Sign-in; exits to identity provider callback or password sign-in.
- **Layout:**
```text
┌────────────────────────────────────────────────────────┐
│ Organisation domain [________________________]         │
│ [ Continue with SSO ]                                   │
└────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Centered form.
- **Components:** Card, Input, Button, Alert.
- **Data and API:** Provider redirect; no PHI.
- **Fields and validation:** `Organisation domain | Input | yes | min 3 chars | Enter your organisation domain.`
- **States:** Provider unavailable, invalid domain, callback error.
- **Interactions and keyboard:** Enter continues; Esc returns to password sign-in.
- **Accessibility and localisation notes:** Provider name is textual.
- **Acceptance criteria:**
  - Given a configured valid domain; When Continue is activated; Then the provider redirect begins.
  - Given an invalid domain; When Continue is activated; Then inline validation blocks redirect.
  - Given callback failure; When the application returns; Then a safe actionable error appears.

### Tenant selection  (route: `/select-tenant`, module: `src/modules/identity-tenancy`, release: R1)
- **Purpose and persona:** Resolve tenant/facility context before protected queries. Personas: multi-context users. Trace: `TEN-001`, `TEN-002`.
- **Entry points and exits:** Post-auth/deep link; exits to home or requested route.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────┐
│ Select hospital / facility                                    │
│ Search [________________]                                     │
│ ○ District Hospital • Main Facility                          │
│ ○ Group Hospital • Facility 2                                │
│ [ Continue ]                                                   │
└────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Radio rows become full-width 44px targets.
- **Components:** Command, RadioGroup, Card, Button.
- **Data and API:** GET `/tenants/me`; no PHI before selection.
- **Fields and validation:** `Tenant | RadioGroup | yes | permitted IDs | Select hospital.`; `Facility | Select | yes | permitted IDs | Select facility.`
- **States:** Loading, empty, expired permission, error.
- **Interactions and keyboard:** Search; arrow; Enter; context committed before protected queries.
- **Accessibility and localisation notes:** Only authorised contexts are enumerated.
- **Acceptance criteria:**
  - Given two accessible contexts; When one is selected; Then only that context is used for subsequent queries.
  - Given expired permission; When Continue is activated; Then the user is returned to context selection.
  - Given a stale deep link; When context is resolved; Then permission is checked before route data loads.

### Platform admin — hospital onboarding  (route: `/platform/tenants/new`, module: `src/modules/platform`, release: R1)
- **Purpose and persona:** Create repeatable tenant onboarding. Persona: platform admin. Trace: `P-ADM-5`, `TEN-010`.
- **Entry points and exits:** Platform admin; exits to setup wizard.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────┐
│ New hospital tenant                          Step 1 of 5          │
│ Legal name [________________] Ownership [Government ▼]            │
│ Facility type [District Hospital ▼]                              │
│ Initial admin [_______________________________]                   │
│ [ Create and continue ]                                          │
└──────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Two-column fields collapse to one.
- **Components:** Form, Input, Select, Progress, Button, Alert.
- **Data and API:** POST `/platform/tenants`; no realtime.
- **Fields and validation:** `Legal name | Input | yes | 2–200 | Required.`; `Ownership | Select | yes | enum | Select ownership.`; `Facility type | Select | yes | enum | Select facility type.`; `Admin email | Input | yes | email | Valid email required.`
- **States:** Draft, validation error, duplicate tenant, server error, success.
- **Interactions and keyboard:** Ctrl+Enter submits.
- **Accessibility and localisation notes:** No PHI in onboarding screens.
- **Acceptance criteria:**
  - Given valid onboarding data; When Create is activated; Then a tenant is created and setup opens.
  - Given a duplicate tenant; When Create is activated; Then conflict is shown and duplicate creation does not occur.
  - Given a missing required field; When Create is activated; Then focus moves to the invalid field.

### Facility setup wizard  (route: `/admin/setup`, module: `src/modules/identity-tenancy`, release: R1)
- **Purpose and persona:** Configure hospital identity, departments, wards, beds, service units, staff positions, reference data, Quality OS applicability and initial manual inputs. Persona: tenant admin. Trace: `P-SET-1`, `SET-001–008`, `SET-013`.
- **Entry points and exits:** Tenant onboarding/Administration; exits to dashboard or next setup step.
- **Layout:**
```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Facility setup  ● 60%   1 Hospital 2 Departments 3 Wards/Beds 4 Services    │
├─────────────────────────────────────────────────────────────────────────────┤
│ [ Current step form/table ]                       [ Import CSV ]             │
│                                                     [ Back ] [Save] [Next]  │
└─────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Stepper scrolls horizontally; tables gain horizontal scroll.
- **Components:** Progress, Tabs, Form, Input, Select, Table, Dialog, Button, Alert.
- **Data and API:** GET setup state/config; step mutations; CSV import. No websocket.
- **Fields and validation:** Department name unique; ward must have parent department; bed code unique; staff designation required; Quality OS initial inputs follow indicator applicability.
- **States:** Resumable, incomplete, saved, CSV validation failure, permission denied.
- **Interactions and keyboard:** Ctrl+S saves; Next validates current step; dirty guard.
- **Accessibility and localisation notes:** Step headings are landmarks; row-level CSV errors include row/field.
- **Acceptance criteria:**
  - Given a partially completed setup; When the user returns; Then the last saved step and completion state are restored.
  - Given a CSV with invalid rows; When Import is activated; Then invalid rows are identified and not committed.
  - Given a configuration edit; When Save is activated; Then effective date and audit history are preserved.

### Configuration history  (route: `/admin/configuration/history`, module: `src/modules/identity-tenancy`, release: R1)
- **Purpose and persona:** Review effective-dated configuration history. Personas: tenant admin/compliance. Trace: `P-SET-2`, `SET-009–012`.
- **Entry points and exits:** Administration; exits to current config/detail.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────┐
│ Configuration history                                                │
│ Entity [All] User [All] Date [________]                              │
│ Date | Entity | Change | Effective | Actor | View                    │
└──────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Filter bar wraps; table scrolls.
- **Components:** FilterBar, DataTable, Sheet, AuditTrailDrawer, Calendar.
- **Data and API:** GET `/configuration/history`; no realtime.
- **Fields and validation:** Date range valid; entity/user filters optional.
- **States:** Empty, historical read-only, stale, permission denied.
- **Interactions and keyboard:** `/` focuses filters; Enter opens row.
- **Accessibility and localisation notes:** Changes are textual, timestamps explicit.
- **Acceptance criteria:**
  - Given history exists; When a tenant filter is applied; Then only tenant-scoped results appear.
  - Given a historical row; When it is opened; Then its values are read-only.
  - Given an edit with a conflicting effective date; When saved; Then the conflict is explained before mutation.

### Users administration  (route: `/admin/users`, module: `src/modules/identity-tenancy`, release: R1)
- **Purpose and persona:** Manage tenant users and role assignments. Persona: tenant admin. Trace: `P-ADM-1`, `TEN-004/006/008`.
- **Entry points and exits:** Administration; exits to user detail/role view.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────┐
│ Users                                           [ Invite user ]       │
│ Search [____] Role [All] Status [All]                               │
│ Name | Role | Department | Status | Last sign-in | Action             │
└────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Row actions become Sheet actions.
- **Components:** DataTable, FilterBar, Form, Dialog, Select, Badge.
- **Data and API:** GET `/users`; server-side paging; mutations; no realtime.
- **Fields and validation:** Name 2–200; email valid; role must be permitted; department conditional.
- **States:** Loading, empty, invite pending, disabled, read-only, error.
- **Interactions and keyboard:** `n` invite; Enter opens row; Ctrl+S saves.
- **Accessibility and localisation notes:** Privilege changes are described in text.
- **Acceptance criteria:**
  - Given valid user data; When Save is activated; Then the role/user state is persisted and audited.
  - Given a privilege escalation; When Save is activated; Then explicit confirmation appears.
  - Given server paging; When the page changes; Then no cross-tenant row appears.

### Roles administration  (route: `/admin/roles`, module: `src/modules/identity-tenancy`, release: R1)
- **Purpose and persona:** Manage tenant RBAC roles. Personas: tenant/platform admin. Trace: `P-ADM-1`, `TEN-004`.
- **Entry points and exits:** Administration; exits to role detail.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────┐
│ Roles                                                    │
│ Registration clerk     24 permissions     View            │
│ Doctor                 41 permissions     View            │
│ Tenant admin           68 permissions     Edit            │
└──────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Permission groups use accordion.
- **Components:** DataTable, Checkbox, Accordion, Button.
- **Data and API:** GET/PATCH `/roles/:id`; no realtime.
- **Fields and validation:** Role name 2–100; permission set valid and authorised.
- **States:** System role read-only, custom role editable, conflict.
- **Interactions and keyboard:** Tab through grouped permissions; Ctrl+S.
- **Accessibility and localisation notes:** Every permission has visible label/group.
- **Acceptance criteria:**
  - Given an editable role; When a permission changes and Save is activated; Then the new set is persisted.
  - Given a system role; When Edit is activated; Then controls remain read-only.
  - Given an unauthorised permission response; When data loads; Then the UI does not grant it.

### Departments administration  (route: `/admin/departments`, module: `src/modules/identity-tenancy`, release: R1)
- **Purpose and persona:** Configure OPD/IPD-enabled departments. Persona: tenant admin. Trace: `P-REG-9`, `P-ADM-1`, `SET-002`.
- **Entry points and exits:** Setup/Administration; exits to wards or registration.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────┐
│ Departments                              [ Add department ] │
│ Name | OPD | IPD | Active | Effective | Action              │
└──────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Each row can open a detail Sheet.
- **Components:** DataTable, Dialog, Form, Switch, Calendar.
- **Data and API:** GET/PATCH `/departments`; no realtime.
- **Fields and validation:** Name unique; OPD/IPD flags boolean; effective date required on change.
- **States:** Empty, active, inactive, validation error, read-only.
- **Interactions and keyboard:** `d` adds; Enter saves.
- **Accessibility and localisation notes:** Switches have state text.
- **Acceptance criteria:**
  - Given an active department; When registration opens; Then it is present in the configured department selector.
  - Given a historically used department; When deactivated; Then it is retained and marked inactive.
  - Given duplicate name; When Save is activated; Then inline error blocks save.

### Wards and beds administration  (route: `/admin/wards-beds`, module: `src/modules/identity-tenancy`, release: R1)
- **Purpose and persona:** Configure wards/beds and functional status. Persona: tenant admin. Trace: `P-ADM-1`, `SET-003`, `SET-011`, `SET-013`.
- **Entry points and exits:** Setup/Administration; exits to bed board.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────┐
│ Wards & beds                      [ Add ward ] [ Import CSV ]       │
│ Dept [Medicine] Ward [Female]                                      │
│ Bed | Class | Functional | Current status | Effective | Action     │
└────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Bed rows can become stacked cards.
- **Components:** DataTable, FilterBar, Select, Switch, Dialog, Alert.
- **Data and API:** GET wards/beds; CSV validation; no realtime.
- **Fields and validation:** Ward parent required; bed code unique; functional boolean.
- **States:** Empty, occupied, non-functional, import preview/error, read-only.
- **Interactions and keyboard:** Import requires preview; occupied state protected.
- **Accessibility and localisation notes:** Bed status is text, not colour only.
- **Acceptance criteria:**
  - Given a non-functional bed; When admission is attempted; Then that bed is not selectable.
  - Given a CSV with a duplicate bed; When previewed; Then the row is flagged before commit.
  - Given an occupied bed; When edited; Then occupancy cannot be silently cleared.

### Patient registry — search/register  (route: `/patients`, module: `src/modules/patient_registry`, release: R1)
- **Purpose and persona:** Search/register patients, issue UHID and support department selection. Persona: registration clerk/admin. Trace: `P-REG-1/2/9`, `REG-001–013`.
- **Entry points and exits:** Patients nav/Ctrl+K; exits to patient profile, duplicate review or completion.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Patients                                         [ New patient ]          │
│ Search [UHID/name/mobile/ABHA] [Search]                                │
│ UHID | Name | Age/Sex | Mobile | ABHA | Status | Open                    │
├──────────────────────────────────────────────────────────────────────────┤
│ New-patient form appears after explicit action                            │
└──────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Form becomes single column; sticky PatientBanner.
- **Components:** Command, DataTable, FilterBar, Form, PatientBanner, UhidBadge, AbhaStatusBadge, Dialog.
- **Data and API:** GET `/patients`; POST `/patients`; server search; no realtime.
- **Fields and validation:** Search one criterion; name 2–200; mobile configured; DOB or approximate age; department required for OP intake.
- **States:** Loading, no results, probable duplicate, provisional, verified, server error.
- **Interactions and keyboard:** F2 search, F4 new, arrows/Enter, Ctrl+Enter.
- **Accessibility and localisation notes:** UHID is announced before name; sensitive identifiers are minimised.
- **Acceptance criteria:**
  - Given a returning patient; When UHID is searched; Then the existing patient opens without creating another UHID.
  - Given a probable duplicate; When new save is attempted; Then duplicate review blocks creation.
  - Given no department; When save is attempted; Then department receives focus and submission is blocked.

### Duplicate review  (route: `/patients/duplicates/:id`, module: `src/modules/patient_registry`, release: R1)
- **Purpose and persona:** Resolve probable duplicate before create. Persona: clerk/registry admin. Trace: `P-REG-2`, `REG-003`.
- **Entry points and exits:** Patient registration duplicate warning; exits to existing record, merge or approved new record.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────┐
│ Possible duplicate                                            │
│ New record              Candidate                              │
│ Name/DOB/mobile         UHID/name/DOB/mobile                   │
│ [Open existing] [Merge/Review] [Continue new]                  │
└────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Comparison columns stack vertically.
- **Components:** Card, PatientBanner, UhidBadge, RadioGroup, Textarea, Button.
- **Data and API:** GET candidates; POST resolution; audit event; no realtime.
- **Fields and validation:** Decision required; reason conditional, 10–500 chars.
- **States:** No candidate, strong match, multiple matches, permission restricted.
- **Interactions and keyboard:** Enter opens chosen path; no silent new-record continuation.
- **Accessibility and localisation notes:** Candidate comparison has deterministic reading order.
- **Acceptance criteria:**
  - Given one strong candidate; When Open existing is selected; Then the matched patient opens.
  - Given multiple candidates; When Merge/Review is selected; Then merge flow opens.
  - Given Continue new; When policy requires a reason; Then reason is required before proceeding.

### Patient merge  (route: `/patients/merge`, module: `src/modules/patient_registry`, release: R1)
- **Purpose and persona:** Merge duplicate records with full history and audit. Persona: authorised registry admin. Trace: `REG-004`.
- **Entry points and exits:** Duplicate review; exits to surviving record or cancel.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Merge records — HIGH RISK                                               │
│ PRIMARY UHID-000124   SECONDARY UHID-000987                              │
│ Demographics | ABHA | Encounters | Documents                            │
│ Type MERGE [______] Reason [________________] [Merge records]            │
└──────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Side-by-side data stacks.
- **Components:** Table, RadioGroup, Input, Textarea, Dialog, AuditTrailDrawer.
- **Data and API:** GET candidates; POST merge; never optimistic.
- **Fields and validation:** Primary required; confirmation exact `MERGE`; reason ≥10 chars.
- **States:** Preview, conflict, permission denied, server error, success.
- **Interactions and keyboard:** Merge disabled until all guards pass.
- **Accessibility and localisation notes:** High-risk warning is textual and focus-managed.
- **Acceptance criteria:**
  - Given valid primary and confirmation; When Merge is activated; Then one surviving UHID is returned with audit trail.
  - Given incorrect confirmation phrase; When Merge is activated; Then mutation is blocked.
  - Given merge conflict; When server responds; Then the original records remain unmodified.

### Patient profile / UHID  (route: `/patients/:uhid`, module: `src/modules/patient_registry`, release: R1)
- **Purpose and persona:** Show patient identity, verification and authorised cross-module entry points. Persona: permitted hospital users. Trace: `REG-001`, `REG-006/007`.
- **Entry points and exits:** Patient search/tab/deep link; exits to OPD/IPD/EMR/audit/ABHA.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ UHID-000124  Asha L  42/F  [Verified] [ABHA linked]                      │
├──────────────────────────────────────────────────────────────────────────┤
│ Demographics | ABHA | Visits | Documents | Access history               │
│ [Start OPD] [Admit] [View EMR] [Who accessed this record]                │
└──────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: PatientBanner remains sticky.
- **Components:** PatientBanner, UhidBadge, AbhaStatusBadge, Tabs, Button, AuditTrailDrawer.
- **Data and API:** GET `/patients/:uhid`; cached by tenant/facility/UHID; no realtime.
- **Fields and validation:** Read-only identity state from server schema.
- **States:** Loading, provisional, verified, missing, denied, stale.
- **Interactions and keyboard:** Patient tab remains active across module changes.
- **Accessibility and localisation notes:** UHID precedes name; sensitive IDs are permission gated.
- **Acceptance criteria:**
  - Given an existing patient; When profile loads; Then UHID and verification state are visible.
  - Given provisional status; When profile loads; Then Provisional is visible and verification action is available.
  - Given denied access; When route opens; Then protected data remains hidden.

### ABHA create/verify at counter  (route: `/patients/:uhid/abha`, module: `src/modules/abdm`, release: R1)
- **Purpose and persona:** Create/verify ABHA linkage. Persona: registration clerk. Trace: `P-REG-7`, `REG-009`.
- **Entry points and exits:** Patient profile; exits to profile/registration.
- **Layout:**
```text
┌─────────────────────────────────────────────────────────────┐
│ ABHA status: Not linked                                     │
│ ABHA number [______________] [ Verify ]                     │
│ [ Start supported ABHA creation ]                           │
│ Consent purpose: care delivery at <facility>                │
└─────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Full-width input/CTA.
- **Components:** PatientBanner, AbhaStatusBadge, Input, Checkbox, Button, Alert.
- **Data and API:** POST `/abdm/abha/verify`; no websocket.
- **Fields and validation:** ABHA conditional; consent boolean required for applicable flow.
- **States:** Not linked, pending, verified, mismatch, gateway unavailable.
- **Interactions and keyboard:** No success until server acknowledgement.
- **Accessibility and localisation notes:** Consent text is visible and labelled.
- **Acceptance criteria:**
  - Given a valid ABHA; When Verify succeeds; Then status becomes verified.
  - Given gateway failure; When Verify is attempted; Then failure is visible and counter registration remains available.
  - Given missing consent; When submission occurs; Then the flow is blocked.

### QR management  (route: `/admin/abdm/qr`, module: `src/modules/abdm`, release: R1)
- **Purpose and persona:** Manage facility/counter/department QR codes. Persona: tenant admin. Trace: `P-REG-5/10`, `ABD-001/002`.
- **Entry points and exits:** Administration; exits to QR print/history.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────┐
│ ABDM QR codes                                    [ Generate QR ]      │
│ Facility | Intake | Department | Status | Generated | Action         │
└──────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Row actions use Sheet.
- **Components:** DataTable, FilterBar, Select, Dialog, Badge, Button.
- **Data and API:** GET/POST QR endpoints; no realtime.
- **Fields and validation:** Facility/intake required; department conditional.
- **States:** None, active, revoked, regenerate confirmation, print error.
- **Interactions and keyboard:** Revoke/regenerate require confirmation.
- **Accessibility and localisation notes:** Human-readable facility/intake/department labels accompany QR.
- **Acceptance criteria:**
  - Given an active QR; When Reprint is selected; Then the matching facility/intake metadata appears.
  - Given a revoke confirmation; When the API succeeds; Then status becomes Revoked.
  - Given department-specific QR; When generated; Then intended department mapping is persisted.

### QR poster print  (route: `/abdm/qr/:qrId/print`, module: `src/modules/abdm`, release: R1)
- **Purpose and persona:** Produce printable Scan and Share poster. Persona: tenant admin/print station. Trace: `UI-006`, `ABD-001`.
- **Entry points and exits:** QR management; exits to browser print.
- **Layout:**
```text
┌─────────────────────────────────────────────────────────────┐
│ <FACILITY>                                                  │
│ Scan to register for OPD                                    │
│                         < LARGE QR >                        │
│ Department: General Medicine   Counter: 1                   │
│ Need help? Visit registration counter.                      │
└─────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Screen preview; print CSS uses fixed A4/A3 geometry.
- **Components:** Card, Button, print CSS, local QR renderer.
- **Data and API:** GET QR metadata; no PHI.
- **Fields and validation:** Print language configured.
- **States:** Active, revoked, expired, print error.
- **Interactions and keyboard:** Browser print; no screen controls in print.
- **Accessibility and localisation notes:** Human-readable labels remain outside QR itself.
- **Acceptance criteria:**
  - Given active QR; When Print is activated; Then preview matches facility/intake/department.
  - Given revoked QR; When print route loads; Then printing is blocked.
  - Given translated labels; When preview renders; Then no text is clipped.

### Awaiting verification queue  (route: `/registration/awaiting-verification`, module: `src/modules/abdm`, release: R1)
- **Purpose and persona:** Review self-registered patients requiring verification. Persona: registration clerk. Trace: `P-REG-4`, `REG-006`, `ABD-009`.
- **Entry points and exits:** Registration nav; exits to verification detail.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Awaiting verification                         Updated 10:32:14              │
│ Received | Name | Match | Candidates | Dept | Age | Action                 │
│ 10:31 | Asha L | Possible | 2 | Medicine | 42 | Review                   │
│ [ Refresh now ]                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Table becomes cards only when row identity remains clear.
- **Components:** DataTable, FilterBar, Badge, Button, ErrorRecovery.
- **Data and API:** GET `/registration/awaiting-verification`; poll **5 s**; show last updated; no websocket.
- **Fields and validation:** Status/search filters optional.
- **States:** Loading, empty, stale >15 s, gateway degraded.
- **Interactions and keyboard:** Enter opens row; manual Refresh available.
- **Accessibility and localisation notes:** ABHA identifier minimised in list.
- **Acceptance criteria:**
  - Given a new callback is persisted; When the next 5 s poll succeeds; Then the row appears.
  - Given 3 consecutive poll failures; When the screen remains open; Then Stale is shown with last update.
  - Given no pending registrations; When loaded; Then empty state explains completion removes entries.

### Self-registration verification/completion  (route: `/registration/awaiting-verification/:id`, module: `src/modules/abdm`, release: R1)
- **Purpose and persona:** Resolve match and complete registration. Persona: registration clerk. Trace: `P-REG-4`, `ABD-008–011`.
- **Entry points and exits:** Verification queue; exits to patient profile/OP slip.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Verify self-registration                                                    │
│ Shared profile                  Candidate patient(s)                        │
│ Name/DOB/mobile/ABHA            UHID/name/match factors                     │
│ Department [Medicine]  Missing [________]                                   │
│ [Link existing] [Complete provisional] [Reject]                             │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Comparison panels stack.
- **Components:** PatientBanner, Table, RadioGroup, Form, Button, Alert, Dialog.
- **Data and API:** GET queue item/candidates; POST verification decision; token response from API.
- **Fields and validation:** Decision required; department required; conditional missing fields; verified/provisional status.
- **States:** Strong match, multiple candidates, no match, stale callback, server error.
- **Interactions and keyboard:** No auto-link for ambiguous match; Ctrl+Enter completes after validation.
- **Accessibility and localisation notes:** Consent timestamp visible when supplied.
- **Acceptance criteria:**
  - Given exactly one strong match; When Link existing is activated; Then patient is linked/verified and token issued.
  - Given multiple candidates; When no candidate is selected; Then link action is blocked.
  - Given no candidate; When Complete provisional is selected; Then a provisional patient is created.

### Counter token display (kiosk)  (route: `/kiosk/tokens/:displayId`, module: `src/modules/platform`, release: R1)
- **Purpose and persona:** Display called token without login. Persona: kiosk viewer. Trace: `UI-003`, `P-REG-6`, `P-RT-4`.
- **Entry points and exits:** Configured kiosk URL; remains open.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ ZMC HOSPITAL — OPD                                     10:32:14            │
│                         NOW SERVING                                         │
│                              M-042                                          │
│                           COUNTER 3                                         │
│ Updated 10:32:14 • Reconnecting automatically                              │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Kiosk only; full-screen.
- **Components:** TokenCard, Badge, ErrorRecovery.
- **Data and API:** GET kiosk tokens; poll **2 s**; last updated; no websocket; scoped kiosk token.
- **Fields and validation:** No interactive user data.
- **States:** Initial, no tokens, network error, stale >6 s, kiosk token expired.
- **Interactions and keyboard:** No login prompt.
- **Accessibility and localisation notes:** Large type; patient names not required in public view.
- **Acceptance criteria:**
  - Given token changes; When a 2 s poll succeeds; Then called token updates.
  - Given two failed polls; When network remains down; Then last good value and reconnecting state remain.
  - Given expired kiosk token; When server rejects; Then safe configuration error appears without login UI.

### OP slip  (route: `/print/op-slip/:visitId`, module: `src/modules/printing`, release: R1)
- **Purpose and persona:** Print registration/visit slip. Persona: registration clerk/print station. Trace: `REG-011`, `UI-006`.
- **Entry points and exits:** Registration completion; exits to print dialog.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────┐
│ <FACILITY>                                                 │
│ OP SLIP                                                    │
│ UHID: 000124     Token: M-042                              │
│ Asha L • 42/F                                              │
│ General Medicine • 02/10/2026 10:31                        │
│ ABHA: Linked                                               │
└────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Screen preview uses same print template.
- **Components:** Card, Badge, Button, print CSS.
- **Data and API:** GET visit snapshot; no mutation.
- **Fields and validation:** Print language configured; copies 1–3.
- **States:** Preview, not found, print failure.
- **Interactions and keyboard:** Enter triggers print.
- **Accessibility and localisation notes:** Screen-only controls are omitted from print.
- **Acceptance criteria:**
  - Given valid visit; When print is initiated; Then UHID/token/department/date appear.
  - Given visit not found; When route loads; Then blank printing is prevented.
  - Given translated language; When preview renders; Then content remains inside printable area.

### Registration configuration  (route: `/admin/registration-config`, module: `src/modules/patient_registry`, release: R1)
- **Purpose and persona:** Configure token series, slip printing and scheme/category fields. Persona: tenant admin. Trace: `P-REG-8`.
- **Entry points and exits:** Administration; exits to preview/save.
- **Layout:**
```text
┌─────────────────────────────────────────────────────────────────┐
│ Registration configuration                                     │
│ Token Prefix [M] Start [001] Reset [Daily]                     │
│ OP slip [ABHA] [scheme] [category] [logo]                     │
│ [Preview slip]                                      [Save]     │
└─────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Sections stack.
- **Components:** Tabs, Form, Input, Select, Switch, Button, Sheet.
- **Data and API:** GET/PATCH config; no realtime.
- **Fields and validation:** Prefix 1–10 alphanumeric; start integer ≥1; reset cadence configured.
- **States:** Dirty, validation error, conflict, read-only.
- **Interactions and keyboard:** Ctrl+S; preview is Sheet, not nested modal.
- **Accessibility and localisation notes:** Configured labels are externalised.
- **Acceptance criteria:**
  - Given valid token configuration; When Save succeeds; Then subsequent registration uses it.
  - Given a conflicting series; When Save is attempted; Then conflict is shown and publish does not occur.
  - Given a disabled slip field; When Preview opens; Then that field is absent.

### Audit log viewer  (route: `/admin/audit`, module: `src/modules/audit`, release: R1)
- **Purpose and persona:** Show immutable access/change events. Personas: compliance officer/admin. Trace: `P-ADM-3`, `AUD-001–004`.
- **Entry points and exits:** Administration; exits to audit detail.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Audit log                                                                  │
│ Actor [ ] Action [ ] Subject UHID [ ] Date [ ]                            │
│ Time | Actor | Subject | Action | Source | Reason | Result | View          │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Filters wrap.
- **Components:** DataTable, FilterBar, AuditTrailDrawer, Badge.
- **Data and API:** GET `/audit/events`; server paging; no realtime.
- **Fields and validation:** UHID optional; date range valid.
- **States:** Loading, empty, denied, read-only.
- **Interactions and keyboard:** `/` focuses filters; Enter opens row.
- **Accessibility and localisation notes:** Actor/time/action/source/reason are text.
- **Acceptance criteria:**
  - Given audit events exist; When UHID filter is applied; Then only matching tenant events show.
  - Given an event is opened; When the drawer renders; Then actor/time/action/source/reason are visible.
  - Given edit is attempted; When the screen is active; Then no edit/delete controls exist.

### Patient access history  (route: `/patients/:uhid/audit`, module: `src/modules/audit`, release: R1)
- **Purpose and persona:** Show who accessed a patient record. Persona: compliance officer. Trace: `P-ADM-3`, `AUD-003`.
- **Entry points and exits:** Patient profile; exits back to patient.
- **Layout:**
```text
┌───────────────────────────────────────────────────────────────┐
│ Who accessed this record: UHID-000124                        │
│ Time | User | Action | Source | Reason                       │
└───────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Table may stack.
- **Components:** PatientBanner, DataTable, AuditTrailDrawer.
- **Data and API:** GET `/patients/:uhid/audit`; no realtime.
- **Fields and validation:** Optional date/action filters.
- **States:** Loading, empty, denied.
- **Interactions and keyboard:** Enter opens audit detail.
- **Accessibility and localisation notes:** UHID is in heading.
- **Acceptance criteria:**
  - Given authorised compliance user; When page loads; Then access events are visible.
  - Given unauthorised user; When page loads; Then no patient access events are disclosed.
  - Given no events; When page loads; Then empty state identifies selected period.

### Break-glass flow  (route: `/patients/:uhid/break-glass`, module: `src/modules/audit`, release: R1)
- **Purpose and persona:** Activate emergency access with recorded reason. Persona: configured clinician. Trace: `P-ADM-4`, `TEN-007`.
- **Entry points and exits:** Normal access denied but break-glass policy allows; exits to patient context with active state.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────┐
│ Emergency access                                            │
│ Patient: UHID-000124                                       │
│ Reason [________________________________________]           │
│ [I understand access is audited] [Activate access]          │
└──────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Full-width form.
- **Components:** PatientBanner, Textarea, Checkbox, Alert, Button.
- **Data and API:** POST `/access/break-glass`; audit reference returned; no realtime.
- **Fields and validation:** Reason 10–500; acknowledgement true.
- **States:** Validation, policy blocked, timeout, success.
- **Interactions and keyboard:** Ctrl+Enter only after guards pass.
- **Accessibility and localisation notes:** Critical warning is textual.
- **Acceptance criteria:**
  - Given valid reason and acknowledgement; When Activate is selected; Then break-glass active state and audit reference appear.
  - Given short reason; When Activate is selected; Then focus moves to reason and access is blocked.
  - Given policy denial; When server responds; Then patient data remains hidden.

### Notification centre  (route: `/notifications`, module: `src/modules/platform`, release: R1)
- **Purpose and persona:** Review persisted notifications. Persona: all authenticated users. Trace: `P-RT-1`, `PLT-001/007`.
- **Entry points and exits:** Bell/deep link; exits to source/acknowledgement.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────┐
│ Notifications [All] [Unread] [Critical]                           │
│ ● Critical: Break-glass access recorded                           │
│ ● Data quality: 2 missing dispositions                            │
│ ○ Info: nightly processing complete                               │
│ Updated 10:32:14                                                   │
└────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Notifications become a full-width Sheet from bell.
- **Components:** Tabs, ScrollArea, Badge, Alert, Button.
- **Data and API:** GET `/notifications`; **WebSocket allowed only here**; persisted state first; REST fallback after 10 s.
- **Fields and validation:** Severity/status filters optional.
- **States:** Loading, empty, reconnecting, REST fallback, critical unacknowledged.
- **Interactions and keyboard:** Enter opens; `r` read; `a` acknowledges critical.
- **Accessibility and localisation notes:** Critical announcements are limited to urgent items.
- **Acceptance criteria:**
  - Given persisted notification; When socket reconnects; Then notification remains available.
  - Given socket loss >10 s; When fallback runs; Then REST refetch restores state.
  - Given unacknowledged critical notification; When authorised user acknowledges; Then actor/time are persisted.

## 8. Screen specifications for R2 (Core clinical)

R2 uses the shared patient identity to drive OPD encounters, inpatient care, EMR and basic billing. Clinical orders, bed allocation, discharge and payments are confirmed-state workflows; they are never represented as saved before server confirmation. [SRS UI-007, NFR-REL-001]

### OPD dashboard  (route: `/opd`, module: `src/modules/opd`, release: R2)
- **Purpose and persona:** Manage department/doctor queues, appointments and tokens. Persona: OPD doctor/registration clerk. Trace: `P-OPD-1`, `OPD-001–004`, `P-RT-4`.
- **Entry points and exits:** OPD navigation, patient registration; exits to consultation or appointment detail.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ OPD — General Medicine            Doctor [Dr X]       Updated 10:32:10     │
├───────────────┬─────────────────────────────────┬───────────────────────────┤
│ Queue 24      │ NOW SERVING M-042              │ Today 46                 │
│ M-041         │ Next M-043                      │ Appointments             │
│ M-042         │ [Call] [Start consultation]     │ Wait-time summary         │
│ M-043         │                                 │                           │
└───────────────┴─────────────────────────────────┴───────────────────────────┘
```
Tablet/variant notes: Queue and appointment cards stack; no websocket.
- **Components:** TokenCard, DataTable, FilterBar, Badge, Button.
- **Data and API:** GET queue/appointments; TanStack Query; poll **10 s**; last updated; no websocket. Queue status remains persisted server state.
- **Fields and validation:** Department required and from configured OPD departments; doctor conditional; priority optional/configured.
- **States:** Loading, empty queue, stale >30 s, error, read-only.
- **Interactions and keyboard:** `J/K` queue; Enter opens selected patient; Call is permission gated.
- **Accessibility and localisation notes:** Tokens are text. Stale state is textual.
- **Acceptance criteria:**
  - Given a new token is registered; When the 10 s refetch succeeds; Then the queue contains it.
  - Given 3 consecutive failed polls; When the page remains open; Then Stale and last-updated state are visible.
  - Given a doctor selects M-042; When consultation opens; Then PatientBanner matches the selected encounter.

### OPD doctor consultation  (route: `/opd/consultation/:encounterId`, module: `src/modules/opd`, release: R2)
- **Purpose and persona:** Put queue, patient history, structured consultation notes and prescription on one screen. Persona: OPD doctor. Trace: `P-OPD-1`, `P-OPD-2`, `OPD-005`, `OPD-007`, `OPD-008`.
- **Entry points and exits:** OPD dashboard; exits to completed encounter/EMR/follow-up.
- **Layout:**
```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ PatientBanner: UHID-000124  Asha L  42/F  Verified                         │
├────────────┬────────────────────────────────────────────────────────────────┤
│ Queue      │ HISTORY / ALERTS / ACTIVE MEDICATIONS                         │
│ M-041      ├────────────────────────────────────────────────────────────────┤
│ M-042      │ Chief complaint [ ]  Hx [ ]  Exam [ ]  Assessment [ ]          │
│ M-043      │ Diagnosis [coded]                                               │
│            │ Prescription [drug] [dose] [route] [frequency] [days]          │
│            │ Follow-up [date]   [Save draft] [Complete encounter]           │
└────────────┴────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: History collapses into accordion; bottom action bar holds Save/Complete.
- **Components:** PatientBanner, DataTable, Tabs, Form, Command, Textarea, Select, Button.
- **Data and API:** GET encounter + longitudinal history. Query keys `opd.encounter`, `emr.summary`. Save mutation; no websocket. Prescription status remains unconfirmed until server response. [OPD-005]
- **Fields and validation:** Chief complaint required; coded diagnosis required; medication fields conditional; follow-up optional.
- **States:** Loading history, draft, saving, server-confirmed, validation error, read-only, offline draft only.
- **Interactions and keyboard:** `J/K`, Alt+H, Alt+P, Ctrl+S, Ctrl+Enter.
- **Accessibility and localisation notes:** History and active medications have table headers and headings; dynamic queue changes do not steal focus.
- **Acceptance criteria:**
  - Given correct encounter context; When required notes are completed and Complete is activated; Then encounter completion is confirmed by the server.
  - Given incomplete prescription; When Complete is activated; Then validation blocks completion and identifies missing prescription fields.
  - Given server response is delayed; When Save is activated; Then the UI says `Awaiting server confirmation` rather than `Saved`.

### IPD admission  (route: `/ipd/admissions/new`, module: `src/modules/ipd`, release: R2)
- **Purpose and persona:** Admit under the appropriate department and allocate a specific functional bed. Persona: nurse/doctor/ward in-charge. Trace: `P-IPD-1`, `P-IPD-5`, `IPD-001/012`.
- **Entry points and exits:** OPD/emergency/patient profile; exits to bed board/admission.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────┐
│ Admit patient                                                       │
│ PatientBanner                                                      │
│ Department [Medicine] → Ward [Female] → Bed [F12]                 │
│ Source [OPD]  Diagnosis [____________]                             │
│ Responsible clinician [____________]                               │
│ [Check availability]                              [Admit]          │
└────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Single-column; BedTile list is touch-optimised.
- **Components:** PatientBanner, Form, Select, Command, BedTile, Alert, Button.
- **Data and API:** GET patient/configured department/ward/bed; POST admission atomically; no websocket.
- **Fields and validation:** Department/ward/bed required; bed must be functional and available; diagnosis/source/clinician required per SRS.
- **States:** Bed unavailable race, validation error, server error, final-admit offline disabled.
- **Interactions and keyboard:** Alt+B opens bed board; Ctrl+Enter after availability validation.
- **Accessibility and localisation notes:** Bed availability is textual; selected bed is repeated in confirmation.
- **Acceptance criteria:**
  - Given functional available bed F12; When Admit succeeds; Then admission and bed allocation are persisted.
  - Given another user allocates F12 first; When this user submits; Then conflict is returned and patient is not assigned twice.
  - Given department and ward do not match; When Admit is activated; Then server validation blocks completion.

### IPD bed board  (route: `/ipd/bed-board`, module: `src/modules/ipd`, release: R2)
- **Purpose and persona:** Show ward occupancy and available/non-functional beds. Persona: nurse/ward in-charge/MS. Trace: `P-IPD-1`, `P-IPD-2`, `IPD-002/003`, `P-RT-4`.
- **Entry points and exits:** IPD navigation/admission.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Bed board — Female Ward                      Updated 10:32:10              │
│ Available 08  Occupied 31  Reserved 02  Non-functional 02                 │
│ [F01 Occupied Asha L] [F02 Available] [F03 Reserved] [F04 Non-functional] │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: BedTile grid wraps.
- **Components:** FilterBar, BedTile, Badge, Card.
- **Data and API:** GET `/ipd/beds`; poll **10 s**; last updated; no websocket.
- **Fields and validation:** Ward required; status filter optional.
- **States:** Loading, empty, stale >30 s, error, partial.
- **Interactions and keyboard:** Enter opens bed; refresh button available.
- **Accessibility and localisation notes:** Occupied patient name is permission gated; status text always present.
- **Acceptance criteria:**
  - Given a bed becomes occupied; When the next poll succeeds; Then its status changes.
  - Given three poll intervals fail; When viewing continues; Then Stale is visible.
  - Given a non-authorised user; When an occupied bed is opened; Then patient details are withheld.

### Midnight census  (route: `/ipd/census`, module: `src/modules/ipd`, release: R2)
- **Purpose and persona:** Review midnight census snapshots by ward/facility. Persona: ward in-charge, MS, quality manager. Trace: `P-IPD-2`, `IPD-005`.
- **Entry points and exits:** IPD navigation/Quality drill-through.
- **Layout:**
```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Midnight census — 02/10/2026                                               │
│ Ward | Functional beds | Midnight count | Capture time | Status            │
│ Female | 40 | 31 | 00:00:12 | Captured                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Filters wrap.
- **Components:** DataTable, FilterBar, Badge, Calendar.
- **Data and API:** GET census snapshots; no websocket. If current snapshot is absent, show data-quality warning.
- **Fields and validation:** Date required; ward optional.
- **States:** Missing snapshot, captured, incomplete, locked/read-only.
- **Interactions and keyboard:** `r` refreshes; date picker keyboard accessible.
- **Accessibility and localisation notes:** `Midnight census` and capture timestamp are literal text.
- **Acceptance criteria:**
  - Given a captured snapshot; When selected; Then midnight count and capture time display.
  - Given no snapshot; When current date opens; Then missing-data warning is shown.
  - Given a locked quality period; When census is opened; Then the historical data is read-only.

### IPD transfer  (route: `/ipd/transfers/new`, module: `src/modules/ipd`, release: R2)
- **Purpose and persona:** Transfer a patient between beds/wards/departments with reason and timestamp. Persona: ward in-charge/clinician. Trace: `P-IPD-6`, `IPD-004/013`.
- **Entry points and exits:** Patient admission/bed board.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────┐
│ Transfer UHID-000124                                                │
│ From Medicine / Female / F12       To Medicine / Private / P04      │
│ Reason [________________________________________]                    │
│ [Check bed]                                         [Transfer]      │
└──────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Source/destination become stacked sections.
- **Components:** PatientBanner, Select, Textarea, BedTile, Button, Dialog.
- **Data and API:** GET admission/target beds; POST transfer; no optimistic bed move.
- **Fields and validation:** Target dept/ward/bed required; reason ≥5; transfer timestamp server supplied.
- **States:** Bed conflict, invalid target, error, success.
- **Interactions and keyboard:** Alt+T; Check bed before Transfer.
- **Accessibility and localisation notes:** Source and destination repeated in confirmation.
- **Acceptance criteria:**
  - Given available target bed; When Transfer is confirmed; Then patient moves and timestamp/reason persist.
  - Given occupied target bed; When Transfer is activated; Then source assignment remains unchanged.
  - Given missing reason; When Transfer is activated; Then validation blocks submission.

### IPD discharge  (route: `/ipd/discharge/:admissionId`, module: `src/modules/ipd`, release: R2)
- **Purpose and persona:** Complete a safe discharge with mandatory structured disposition and summary. Persona: doctor. Trace: `P-IPD-3`, `P-IPD-4`, `IPD-006/007/010/011`.
- **Entry points and exits:** Admission/ward board; exits to discharge summary/EMR/Quality source.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Discharge — UHID-000124                                                   │
│ Disposition [Routine ▼]   Discharge time [server]                         │
│ Referral destination [ ] (if referred)                                    │
│ Cause of death [ ] (if death)                                             │
│ Summary: Diagnosis • Course • Procedures • Medicines • Advice             │
│ [Preview]                                               [Complete]         │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Conditional sections expand inline, not modal.
- **Components:** PatientBanner, Form, Select/RadioGroup, Textarea, Calendar, Dialog, Button.
- **Data and API:** GET admission summary; POST discharge; no websocket. Server response is the source of truth.
- **Fields and validation:** Disposition required: `routine|LAMA|absconded|referred|death|other as configured`; referral destination required when referred; cause of death required when death; summary required. [IPD-006/007]
- **States:** Missing disposition, conditional validation, server error, locked/read-only.
- **Interactions and keyboard:** Alt+D, Ctrl+Enter. No submit confirmation until form validation passes.
- **Accessibility and localisation notes:** LAMA/absconded are expanded on patient-facing output. Disposition is high prominence.
- **Acceptance criteria:**
  - Given no disposition; When Complete is activated; Then discharge is blocked and disposition receives focus.
  - Given `death`; When Complete is activated without cause of death; Then the cause field is shown and required.
  - Given all required fields valid; When Complete is activated; Then discharge, disposition and time are persisted.

### Discharge summary  (route: `/ipd/discharge/:id/summary`, module: `src/modules/emr`, release: R2)
- **Purpose and persona:** Present the standard discharge summary for review/print. Persona: doctor/print station. Trace: `P-IPD-4`, `UI-006`.
- **Entry points and exits:** Completed discharge; exits to print.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────┐
│ DISCHARGE SUMMARY                                           │
│ Patient / UHID / Admission / Discharge                     │
│ Diagnoses • Procedures • Clinical course                    │
│ Medicines • Follow-up • Disposition                         │
│ Referral / Cause of death where applicable                  │
│ [Print]                                                     │
└──────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Preview sections accordion; print is flat document order.
- **Components:** Card, Accordion, Badge, Button, print CSS.
- **Data and API:** GET discharge snapshot; no mutation.
- **Fields and validation:** Print language + copies.
- **States:** Draft, final, missing required section, print error.
- **Interactions and keyboard:** Enter triggers print.
- **Accessibility and localisation notes:** Section headings are explicit.
- **Acceptance criteria:**
  - Given final discharge; When preview opens; Then required sections are present.
  - Given death disposition; When preview opens; Then cause of death is displayed where recorded.
  - Given non-final discharge; When Print is activated; Then printing is disabled.

### EMR longitudinal record  (route: `/emr/patients/:uhid`, module: `src/modules/emr`, release: R2)
- **Purpose and persona:** Show one longitudinal record across OPD, IPD and available diagnostic records. Persona: clinician. Trace: `P-EMR-1`, `EMR-001–006`.
- **Entry points and exits:** Patient profile, consultation.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ PatientBanner                                                             │
│ Timeline | Problems | Allergies | Medications | Documents                 │
│ 02/10 OPD — General Medicine                                              │
│ 29/09 IPD — Female Ward                                                   │
│ 20/09 Discharge summary                                                   │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Timeline cards stack.
- **Components:** PatientBanner, Tabs, Accordion, DataTable, Badge, Button.
- **Data and API:** GET longitudinal timeline; query by UHID; no websocket.
- **Fields and validation:** Optional date range/type filters.
- **States:** Loading, empty, partial, permission-filtered, error.
- **Interactions and keyboard:** J/K timeline navigation; Enter opens source encounter.
- **Accessibility and localisation notes:** Record type/date are textual.
- **Acceptance criteria:**
  - Given multiple encounters; When page loads; Then records are shown chronologically.
  - Given one source is unavailable; When page loads; Then partial-data state leaves other records visible.
  - Given an encounter is opened; When action activates; Then correct source context is restored.

### Tariffs  (route: `/billing/tariffs`, module: `src/modules/billing-insurance`, release: R2)
- **Purpose and persona:** Configure services and tariff amounts used in bills. Persona: billing admin. Trace: `P-BIL-1`.
- **Entry points and exits:** Billing navigation.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────┐
│ Tariffs                                       [Add service]       │
│ Service | Category | Amount | Effective | Active | Action        │
└──────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Row detail uses Sheet.
- **Components:** DataTable, FilterBar, Form, Input, Select, Switch.
- **Data and API:** GET/PATCH tariffs; no realtime.
- **Fields and validation:** Name 2–200; amount decimal ≥0; effective date required.
- **States:** Loading, empty, conflict, historical read-only.
- **Interactions and keyboard:** Ctrl+S; amount parses Indian grouping before API submission.
- **Accessibility and localisation notes:** Currency shown as INR with configured locale.
- **Acceptance criteria:**
  - Given active tariff; When saved; Then new bills can select it.
  - Given conflicting effective date; When save occurs; Then conflict blocks mutation.
  - Given amount invalid; When save occurs; Then inline numeric error is shown.

### Billing — invoice  (route: `/billing/encounters/:encounterId`, module: `src/modules/billing-insurance`, release: R2)
- **Purpose and persona:** Create invoice from configured tariffs and encounter services. Persona: billing executive. Trace: `P-BIL-1`, `P-BIL-4`.
- **Entry points and exits:** Encounter/charge route; exits to payment.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ PatientBanner                     Invoice #INV-001                         │
│ Service | Qty | Rate | Coverage | Amount                                  │
│ Consultation | 1 | ₹500 | Scheme | ₹0                                    │
│ Lab | 1 | ₹200 | Self | ₹200                                              │
│ Total ₹200                        [Save invoice] [Payment]                 │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Services table scrolls horizontally.
- **Components:** PatientBanner, DataTable, Select, Input, Badge, Button.
- **Data and API:** GET encounter/tariffs; POST invoice; no realtime.
- **Fields and validation:** Service active; quantity integer ≥1; coverage from configured enum.
- **States:** Draft, calculated, save error, patient mismatch, post-payment read-only.
- **Interactions and keyboard:** `+` add service; Ctrl+S.
- **Accessibility and localisation notes:** Coverage is textual.
- **Acceptance criteria:**
  - Given scheme-covered service; When invoice saves; Then covered amount and reason persist.
  - Given wrong patient context; When invoice loads; Then server rejects the mismatched context.
  - Given quantity 0; When save occurs; Then validation blocks.

### Billing — payment and receipt  (route: `/billing/payments/:invoiceId`, module: `src/modules/billing-insurance`, release: R2)
- **Purpose and persona:** Take payment and issue receipt. Persona: billing executive. Trace: `P-BIL-2`, `UI-006`.
- **Entry points and exits:** Invoice; exits to receipt print.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────┐
│ Payment INV-001    Due ₹200                                 │
│ Mode [Cash]    Amount [₹200.00]    Reference [________]    │
│ [Take payment]                                             │
│ Status: Awaiting server confirmation                        │
└──────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Form fields stack.
- **Components:** PatientBanner, Form, Select, Input, Badge, Button.
- **Data and API:** GET invoice; POST payment with idempotency key; no realtime.
- **Fields and validation:** Mode required; amount >0 and ≤due unless configured exception; reference conditional.
- **States:** Pending, duplicate/idempotent retry, failed, paid, overpayment blocked.
- **Interactions and keyboard:** Enter submits; button disabled while request in flight.
- **Accessibility and localisation notes:** Receipt payment identifiers are non-sensitive.
- **Acceptance criteria:**
  - Given due ₹200 and payment ₹200; When confirmed; Then receipt action becomes available.
  - Given network retry; When same payment is retried; Then only one payment remains persisted.
  - Given amount exceeds due; When submit occurs; Then UI blocks unless explicit configured exception exists.

### Government scheme/free-service handling  (route: `/billing/scheme-coverage/:encounterId`, module: `src/modules/billing-insurance`, release: R2)
- **Purpose and persona:** Apply configured free/scheme coverage for government tenants. Persona: government billing/admin. Trace: `P-BIL-4`.
- **Entry points and exits:** Invoice, when tenant profile permits.
- **Layout:**
```text
┌─────────────────────────────────────────────────────────────────┐
│ Coverage                                                        │
│ Patient category [Configured]  Scheme [Configured]             │
│ Service | Coverage | Reason | Amount covered                    │
│ Consultation | Scheme | Eligible | ₹500                         │
│ [Apply coverage]                                                │
└─────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Coverage rows become cards.
- **Components:** PatientBanner, Select, DataTable, Textarea, Button.
- **Data and API:** GET tenant scheme config; POST coverage decision; no realtime.
- **Fields and validation:** Category required; scheme conditional; reason conditional by policy.
- **States:** Not applicable, eligibility unknown, saved, error.
- **Interactions and keyboard:** Explicit patient/scheme context before Apply.
- **Accessibility and localisation notes:** Government labels are configuration-driven.
- **Acceptance criteria:**
  - Given government tenant; When valid coverage is applied; Then invoice reflects the covered amount.
  - Given private tenant; When this route is opened; Then government-only controls are hidden/not enabled.
  - Given eligibility unknown; When Apply is activated; Then no successful coverage state is shown without server confirmation.

## 9. Screen specifications for R3 (Quality OS v1)

Quality OS is source-sensitive and evidence-oriented. The UI exposes the complete supplied catalogue while preserving source provenance, scope, calculation mode, frequency, sampling metadata and historical definitions. [QOS-001–013, QOS-020–022, QOS-050–063]

### Quality home dashboard  (route: `/quality`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Provide an executive/quality-manager view of enabled indicators, data quality, alerts and CAPA. Personas: quality manager, tenant admin, MS/CEO. Trace: `P-QOS-1/4/5/7/9/10`, `QOS-021`, `QOS-050`, `QOS-062`.
- **Entry points and exits:** Quality navigation; exits to catalogue, data quality, alerts, CAPA and period close.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Quality OS  Profile [NQAS ▾]  Period [Sep 2026]  Status [Provisional]       │
├────────────┬────────────┬────────────┬───────────────────────────────────────┤
│ Enabled 356│ Valid 341  │ Exceptions15│ Open CAPA 8                         │
├───────────────────────────────┬──────────────────────────────────────────────┤
│ Headline indicators            │ Data quality                              │
│ BOR 78.2%  ALOS 4.1 days       │ Missing dispositions 4 → Fix at source    │
│ LAMA 1.8%  SSI 2.4%            │ Census gaps 1 → Review                    │
├───────────────────────────────┴──────────────────────────────────────────────┤
│ Trend / alerts / recent CAPA                                                │
└──────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Cards stack; charts move below data-quality panel.
- **Components:** IndicatorCard, StatusPill, RunChart, BarChart, Alert, DataTable, FilterBar, Button.
- **Data and API:** GET snapshot summaries. Query keys `quality.home`, `quality.exceptions`, `quality.capa`. Refetch 30 s; last updated; no websocket.
- **Fields and validation:** Framework required: enabled `NQAS|NABH|both`; period required; department optional.
- **States:** Loading skeleton, no enabled indicators, partial snapshot, provisional, locked, stale >90 s.
- **Interactions and keyboard:** `/` filters; Enter opens indicator; CAPA/alert actions are permission gated.
- **Accessibility and localisation notes:** Every card retains native unit; charts have table toggle; no percentage coercion.
- **Acceptance criteria:**
  - Given NQAS profile enabled; When dashboard loads; Then the 356-indicator baseline is represented without implying every row is applicable/enabled.
  - Given both profiles enabled; When shared semantics qualify; Then a single computed value is shown with dual provenance rather than duplicated cards.
  - Given locked period; When dashboard loads; Then values are labelled Locked and are not editable.

### Indicator catalogue  (route: `/quality/indicators`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Browse/filter the 406 definitions and tenant enablement. Persona: quality manager/admin. Trace: `P-QOS-1/8/9/10/19/20`, `QOS-001/005/006/008/009/010`.
- **Entry points and exits:** Quality dashboard; exits to indicator detail/enablement.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────────┐
│ Indicator catalogue                                  406 definitions           │
│ Framework [NQAS] Edition [District Hospital] Scope [ ]                        │
│ Department/Specialty [ ] Frequency [ ] Calculation mode [ ] Status [ ]        │
│ ID | Name | Scope | Type/Standard | Frequency | Mode | Enabled | Open          │
│ NQAS-DH-001 | Bed Occupancy Rate | district_hospital | Productivity | Monthly │
└────────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: FilterBar becomes Sheet.
- **Components:** FilterBar, DataTable, Badge, Switch, Command, Pagination.
- **Data and API:** GET `/quality/indicators`; server paging; no websocket. JSON-backed fields: `framework`, `scope`, `source_sheet`, `source_serial`, `category`, `name`, `numerator`, `denominator`, `formula_or_operator`, `frequency`, `source_of_data`, `significance`, `capture_route`, `source_reference`; NABH additionally has `standard`, `unit`, `applicability_or_source_note`, `book_page`.
- **Fields and validation:** Framework `NQAS|NABH`; scope `district_hospital|organisational|department_specific`; frequency includes `Monthly`, `Yearly`, `Continuous`, `Monthly, cumulative/YTD`, `—`; calculation mode supports `auto|manual|hybrid` in the model.
- **States:** Loading, empty, filtered, server error, pagination, enabled/disabled.
- **Interactions and keyboard:** `/` filters; `g` opens focused row; Space toggles enablement only with permission.
- **Accessibility and localisation notes:** Source locator is visible text. Current v0.2 JSON has null `type`, `direction`, `calculation_mode` and blank NABH `department_or_specialty`; display `Not populated in v0.2` rather than guessing.
- **Acceptance criteria:**
  - Given framework=NQAS; When the filter is applied; Then 356 rows are available to the server-side catalogue.
  - Given scope=department_specific; When the filter is applied; Then the NABH specialty rows are returned from source scope.
  - Given `calculation_mode` is null in v0.2 JSON; When the row renders; Then the UI displays an explicit unknown state and does not infer Auto/Manual/Hybrid.

### Indicator detail — NQAS Bed Occupancy Rate  (route: `/quality/indicators/NQAS-DH-001`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Show source definition, provenance, native unit, calculated value, trend and drill-through. Persona: quality manager. Trace: `P-QOS-2/3/19/20`, `QOS-002/007/008/021/022/052/060`.
- **Entry points and exits:** Catalogue/dashboard; exits to drill-through, alerts, CAPA or history.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ NQAS-DH-001  Bed Occupancy Rate          Monthly   %   Provisional          │
├───────────────────────────────┬──────────────────────────────────────────────┤
│ Definition / numerator         │ Sep 2026  78.2%                            │
│ Denominator / formula          │ Run chart | Control chart                 │
│ Source: KPI / S No 1           │ Target | Signals | Drill-through           │
└───────────────────────────────┴──────────────────────────────────────────────┘
```
Tablet/variant notes: Definition and chart sections stack.
- **Components:** IndicatorCard, Accordion, RunChart, ControlChart, Badge, DataTable, ProvisionalLockedBadge.
- **Data and API:** GET definition/value/provenance/trend; no websocket.
- **Fields and validation:** Period required; view selector optional.
- **States:** Definition-only, no value, provisional, locked, superseded, not-applicable, invalid denominator, missing inputs.
- **Interactions and keyboard:** `g` from catalogue, `d` drill-through, chart table toggle.
- **Accessibility and localisation notes:** Source formula preserved; unit `%` shown from definition.
- **Acceptance criteria:**
  - Given the NQAS-DH-001 definition; When detail loads; Then the source KPI name, formula, monthly frequency and `%` unit are visible.
  - Given value 78.2%; When the card renders; Then it shows 78.2% and not 0.782.
  - Given a missing denominator; When the value is requested; Then status is Invalid denominator and no numeric result is fabricated.

### Indicator detail — NABH KPI  (route: `/quality/indicators/NABH-ORG-001`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Show NABH organisational KPI metadata and its source capture guidance. Persona: quality manager. Trace: `P-QOS-19/20`, `QOS-040/043/044`.
- **Entry points and exits:** Catalogue; exits to manual/sampling if required.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ NABH-ORG-001  Time for initial assessment of indoor patients   Minutes      │
│ Organisational • PSQ 3a • Monthly                                        │
│ Numerator / Denominator / Source guidance                                  │
│ [Source provenance] [Manual value] [View trend]                            │
└──────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Source guidance uses Accordion.
- **Components:** IndicatorCard, Accordion, RunChart, Badge, Button.
- **Data and API:** GET NABH definition/source metadata; no websocket.
- **Fields and validation:** No patient data fields; action controls depend on calculation/sampling metadata.
- **States:** No value, manual required, sampled, locked, superseded, licensing-limited.
- **Interactions and keyboard:** Enter provenance; `m` manual value when allowed.
- **Accessibility and localisation notes:** If NABH reproduction rights are unresolved, show locator and licensed summary rather than unauthorised text.
- **Acceptance criteria:**
  - Given the NABH-ORG-001 row; When detail loads; Then PSQ 3a, Minutes and source reference are shown.
  - Given source guidance calls for manual/HIS choice; When capture action opens; Then manual pathway is available.
  - Given licensing mode is restricted; When detail loads; Then the UI shows locator/summary without asserting full-text reproduction rights.

### Indicator drill-through  (route: `/quality/indicators/:id/drill-through`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Trace a calculated value to contributing cases, observations or manual evidence. Personas: quality manager/auditor. Trace: `P-QOS-2`, `QOS-051/052`.
- **Entry points and exits:** Indicator value. Exits: read-only source case/evidence.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Drill-through — Emergency Death Rate                                        │
│ Numerator 3 | Denominator 512 | Value 0.59%                                │
│ UHID | Encounter | Event date | Included | Reason | Open                  │
└──────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Patient-level rows can open a full-screen Sheet.
- **Components:** DataTable, FilterBar, PatientBanner, AuditTrailDrawer, Button.
- **Data and API:** GET contributing source IDs; permission filtered; no websocket.
- **Fields and validation:** Period required; inclusion filter optional.
- **States:** Loading, permission-filtered, aggregate-only, empty, audit denied.
- **Interactions and keyboard:** Enter opens read-only source record.
- **Accessibility and localisation notes:** Minimum necessary PHI in list; each patient access is auditable.
- **Acceptance criteria:**
  - Given a numerator of 3; When drill-through opens; Then the included source events are listed if permitted.
  - Given aggregate-only permission; When drill-through opens; Then no patient details are disclosed.
  - Given a source case is opened; When it renders; Then the access is recorded in audit trail.

### Manual indicator entry  (route: `/quality/manual/:id`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Enter source-defined numerator/denominator/count for manual or fallback indicators. Persona: quality manager. Trace: `P-QOS-11`, `QOS-003/011/021/022/044`.
- **Entry points and exits:** Indicator detail. Exits: saved value/status/provenance.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Manual entry — <Indicator>           Period [Sep 2026]                     │
│ Numerator [________]  Denominator [________]  OR Count [________]         │
│ Unit: <source unit>      Evidence [ Upload ]                              │
│ [Save draft]                                      [Submit]                 │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Numeric controls stack; evidence area full width.
- **Components:** Form, Input, Calendar, EvidenceUploader, Badge, Button.
- **Data and API:** GET definition; POST fact input; no optimistic final value.
- **Fields and validation:** Numeric inputs ≥0; required fields depend on source operator; Unit read-only; evidence conditional.
- **States:** Draft, invalid denominator, insufficient input/sample, submitted, locked, superseded.
- **Interactions and keyboard:** Ctrl+S draft; Ctrl+Enter submit.
- **Accessibility and localisation notes:** Unit and calculation operator are visible.
- **Acceptance criteria:**
  - Given a percentage source operator; When numerator/denominator are valid; Then the submission is accepted for calculation.
  - Given a direct-count indicator; When the form opens; Then Count is available without an invented denominator.
  - Given locked period; When Submit is activated; Then mutation is blocked.

### Sampling plans and observations  (route: `/quality/sampling`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Manage source-defined sampling plans and observations. Persona: quality manager/auditor. Trace: `P-QOS-12`, `QOS-004`.
- **Entry points and exits:** Indicator detail. Exits: observation evidence/value.
- **Layout:**
```text
┌───────────────────────────────────────────────────────────────────────────┐
│ Sampling plan                                                             │
│ Indicator [NABH…] Period [ ] Method [Source method] Population [ ]       │
│ Guidance [ ] Planned [ ] Completed [ ] Status [Insufficient sample]     │
│ [Create plan] [Add observation]                                           │
└───────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Observation entry uses a Sheet.
- **Components:** Form, DataTable, Progress, EvidenceUploader, Calendar, Badge.
- **Data and API:** GET sampling metadata; POST plan/observations; no websocket.
- **Fields and validation:** Method must match source guidance; population and planned sample positive.
- **States:** Planned, collecting, sufficient, insufficient, late, locked.
- **Interactions and keyboard:** Create plan validates against source methodology.
- **Accessibility and localisation notes:** Sampling requirement never appears only as an icon.
- **Acceptance criteria:**
  - Given planned 20 and completed 10; When status renders; Then it says Insufficient sample.
  - Given completed reaches the required source sample; When status updates; Then it changes to Sufficient.
  - Given locked period; When an observation is edited; Then the edit is blocked.

### Data-quality centre  (route: `/quality/data-quality`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Expose missing fields, census gaps, invalid denominators, late data, insufficient samples and calculation exceptions with fix-at-source actions. Persona: quality manager. Trace: `P-QOS-7`, `QOS-050`.
- **Entry points and exits:** Quality dashboard. Exits: source module, indicator detail.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Data quality — Sep 2026                                                     │
│ Missing dispositions 4 | Census gaps 1 | Invalid denominators 2            │
│ Type | Severity | Source | Indicator | Count | Fix at source | Status       │
└──────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Metrics stack, table becomes cards.
- **Components:** DataTable, FilterBar, StatusPill, Alert, ErrorRecovery, Button.
- **Data and API:** GET data-quality exceptions; poll/refetch **30 s**; last updated; no websocket. Fix occurs in source module, then Quality OS refetches.
- **Fields and validation:** Severity/status filters optional.
- **States:** Empty/healthy, exceptions present, stale, dependency unavailable, resolved.
- **Interactions and keyboard:** Enter opens source correction.
- **Accessibility and localisation notes:** `Fix at source` is explicit text.
- **Acceptance criteria:**
  - Given missing disposition count 4; When the row opens; Then it links to IPD discharge source field.
  - Given source correction is completed; When Quality OS refetches; Then the resolved count changes.
  - Given dependency failure; When page loads; Then last successful update remains visible.

### Quality alerts  (route: `/quality/alerts`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Review configured target, statistical, missing-data and overdue alerts. Personas: quality manager/recipients. Trace: `P-QOS-4`, `QOS-062`.
- **Entry points and exits:** Dashboard/notification centre. Exits: indicator/CAPA.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Alerts                                                                       │
│ Severity [ ] Trigger [ ] Status [ ]                                        │
│ Time | Indicator | Trigger | Value | Target/UCL | Severity | CAPA          │
└──────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Filter Sheet; row detail full screen.
- **Components:** DataTable, FilterBar, Badge, Alert, Button.
- **Data and API:** GET alerts; normal REST refetch; no websocket. Notification delivery may also surface the persisted alert.
- **Fields and validation:** Status/Severity filters optional.
- **States:** Open, acknowledged, resolved, stale, empty, permission filtered.
- **Interactions and keyboard:** `Alt+C` opens linked CAPA.
- **Accessibility and localisation notes:** Statistical trigger names and values are textual.
- **Acceptance criteria:**
  - Given target breach; When row opens; Then value, target and trigger are visible.
  - Given critical alert unacknowledged; When authorised user acknowledges; Then actor/time are stored.
  - Given resolved alert; When filter=resolved; Then the alert appears.

### Alert configuration  (route: `/quality/alerts/config`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Configure internal thresholds/recipients without editing source formulas. Persona: quality manager/admin. Trace: `P-QOS-4`, `QOS-063`.
- **Entry points and exits:** Alerts. Exits: saved rule/detail.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────┐
│ Alert rule                                                   │
│ Indicator [ ] Trigger [Target breach]                       │
│ Threshold [ ] Consecutive periods [ ] Recipients [ ]       │
│ Source formula: READ ONLY                  [ Save rule ]     │
└──────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Recipients use a searchable multi-select.
- **Components:** Form, Select, Input, Checkbox, Button, Badge.
- **Data and API:** GET/PATCH tenant alert config; no websocket.
- **Fields and validation:** Trigger enum; threshold numeric where applicable; consecutive periods integer ≥1; recipient list authorised.
- **States:** Valid, invalid threshold, conflict, read-only.
- **Interactions and keyboard:** Ctrl+S; no source-definition editing.
- **Accessibility and localisation notes:** Read-only source formula is labelled.
- **Acceptance criteria:**
  - Given a target threshold; When Save succeeds; Then tenant alert config changes.
  - Given source formula field; When focused; Then it is read-only.
  - Given unauthorised recipient; When saved; Then server validation blocks.

### CAPA register  (route: `/quality/capa`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** List CAPAs raised from alerts, incidents, audits, complaints or manual entry. Persona: quality manager. Trace: `P-QOS-5`, `QOS-070–072`.
- **Entry points and exits:** Dashboard/alerts. Exits: CAPA board/detail.
- **Layout:**
```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ CAPA register                                      [Raise CAPA]             │
│ Severity [ ] State [ ] Owner [ ] Due [ ]                                  │
│ ID | Issue | Severity | Owner | Due | State | Indicator                   │
└─────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Filters in Sheet.
- **Components:** DataTable, FilterBar, Badge, Button.
- **Data and API:** GET CAPAs; server paging; refetch **30 s**; no websocket.
- **Fields and validation:** Severity/state/owner optional filters.
- **States:** Open, overdue, closed, read-only, empty.
- **Interactions and keyboard:** Alt+C raises; Enter opens.
- **Accessibility and localisation notes:** State and due date are text.
- **Acceptance criteria:**
  - Given a CAPA in RCA; When State=RCA filter is applied; Then it appears.
  - Given overdue CAPA; When list loads; Then overdue text and due date are visible.
  - Given read-only user; When screen loads; Then Raise CAPA is hidden/disabled according to permission model.

### CAPA board  (route: `/quality/capa/board`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Visualise CAPAs by workflow state while retaining a keyboard-accessible alternative. Persona: quality manager. Trace: `P-QOS-5`, `QOS-072`.
- **Entry points and exits:** CAPA register. Exits: detail.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Raised | RCA | Action plan | Implementation | Verification | Closed         │
│ #101   | #98 | #94         | #91            | #87          | #81            │
└──────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Horizontal scroll; keyboard list view remains available.
- **Components:** Card, Badge, Button, CapaTimeline.
- **Data and API:** GET grouped CAPAs; refetch **30 s**; no websocket.
- **Fields and validation:** Filters inherited from register.
- **States:** Empty columns, stale, read-only.
- **Interactions and keyboard:** State transition uses a button/menu path; never drag-only.
- **Accessibility and localisation notes:** Column headings semantic.
- **Acceptance criteria:**
  - Given CAPA #98 in RCA; When board loads; Then it is in RCA column.
  - Given keyboard-only user; When transition is requested; Then a non-drag control is available.
  - Given CAPA moves state; When refetch succeeds; Then the card appears in its new state.

### CAPA detail  (route: `/quality/capa/:id`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Complete issue→RCA→action→implementation→verification→closure and reopen ineffective CAPA. Persona: quality manager. Trace: `P-QOS-5`, `QOS-071/072`.
- **Entry points and exits:** Register/board/alert. Exits: next state, list.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ CAPA-001  State RCA  Severity Major  Owner QA                              │
│ Issue [ ]  Due [ ]  RCA [ ]                                               │
│ Corrective [ ]  Preventive [ ]  Evidence [Upload]                         │
│ Effectiveness indicator [ ] Re-check [ ]                                  │
│ [Save] [Advance state] [Reopen]                                           │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Timeline at top; actions sticky bottom.
- **Components:** Form, CapaTimeline, EvidenceUploader, Select, Calendar, Textarea, Button, Badge.
- **Data and API:** GET/PATCH CAPA; POST state transition; evidence upload; no websocket.
- **Fields and validation:** Issue ≥10; severity/owner/due required; RCA ≥20 in RCA+; action required in Action Plan; effectiveness indicator/recheck in Verification.
- **States:** Raised, RCA, action plan, implementation, verification, closed, reopened, overdue.
- **Interactions and keyboard:** Advance blocked until state-specific requirements are complete.
- **Accessibility and localisation notes:** Timeline is an ordered list; evidence metadata is accessible.
- **Acceptance criteria:**
  - Given state=RCA and empty RCA; When Advance is activated; Then transition is blocked and RCA receives focus.
  - Given Verification with evidence and effective indicator result; When Advance succeeds; Then state becomes Closed.
  - Given Verification outcome ineffective; When Reopen is activated; Then CAPA returns to RCA.

### Month-end close  (route: `/quality/period-close`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Review completeness and lock an indicator period. Persona: quality manager/authorised approver. Trace: `P-QOS-6`, `QOS-053`.
- **Entry points and exits:** Quality dashboard/reports. Exits: locked period/correction.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Month-end close — Sep 2026                                                 │
│ Completeness 98.7% | Exceptions 3 | Late 1 | Status Provisional            │
│ [Review exceptions] [Recalculate] [Preview report] [Lock period]           │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Actions become a bottom action bar.
- **Components:** Progress, DataTable, ProvisionalLockedBadge, Alert, Dialog, Button.
- **Data and API:** GET period status/exceptions; POST recalc; POST lock; no websocket.
- **Fields and validation:** Period required; lock reason ≥10; approver acknowledgement required.
- **States:** Provisional, blocked, ready, locked, correction/new snapshot.
- **Interactions and keyboard:** Ctrl+Shift+L opens lock review; final confirmation required.
- **Accessibility and localisation notes:** Locked status remains visible across screens.
- **Acceptance criteria:**
  - Given unresolved exceptions; When Lock is activated; Then lock is blocked or explicitly allowed only by documented exception policy.
  - Given all prerequisites pass; When authorised approver confirms; Then period becomes immutable/locked.
  - Given locked period; When Recalculate is selected; Then the UI routes to versioned correction rather than overwriting.

### Locked-period reproduction  (route: `/quality/period-close/:period/reproduce`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Prove that a locked value is reproducible from stored definition version/source inputs. Personas: quality manager/auditor. Trace: `P-QOS-6`, `QOS-054`.
- **Entry points and exits:** Locked period. Exits: comparison result.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Reproduce Sep 2026 — Locked snapshot                                       │
│ Stored | Recomputed | Match | Definition version | Source hash             │
│ BOR 78.2% | 78.2% | Match | v0.2 | <hash>                                 │
│ [Run reproduction]                                                         │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Table stacks.
- **Components:** DataTable, Badge, Accordion, Button.
- **Data and API:** POST background reproduction; status poll **5 s**; no websocket.
- **Fields and validation:** Reason ≥10 required.
- **States:** Queued, running, match, mismatch, source unavailable.
- **Interactions and keyboard:** Run starts job; page polls.
- **Accessibility and localisation notes:** Match/mismatch uses text + marker.
- **Acceptance criteria:**
  - Given stored and recomputed BOR both 78.2%; When job completes; Then Match is shown.
  - Given mismatch; When job completes; Then source hash/definition version remain visible for investigation.
  - Given source unavailable; When job runs; Then the state is `Source unavailable`, not a fabricated value.

### Monthly quality report  (route: `/quality/reports/monthly`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Generate a monthly report from snapshot data. Persona: quality manager. Trace: `P-QOS-14`, `QOS-073`.
- **Entry points and exits:** Dashboard/period close. Exits: print/PDF/report history.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────┐
│ Monthly quality report — Sep 2026                                   │
│ Framework [NQAS] Status [Locked]                                   │
│ Indicators | Exceptions | Alerts | CAPA                             │
│ [Preview] [Generate report]                                        │
└──────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Sections become accordion.
- **Components:** Card, Table, Button, Badge, ProvisionalLockedBadge.
- **Data and API:** GET snapshot; Celery generation job; status poll **5 s**; no websocket.
- **Fields and validation:** Period/framework required.
- **States:** Generating, ready, failed, permission restricted, licensing-limited.
- **Interactions and keyboard:** Generate disabled while same job is running.
- **Accessibility and localisation notes:** Report headers are semantic; licensing limits are explicit.
- **Acceptance criteria:**
  - Given locked NQAS period; When Generate succeeds; Then report contains snapshot values and status.
  - Given job failure; When error occurs; Then retry is offered without generating a blank report.
  - Given restricted NABH text rights; When report renders; Then only permitted summary/locator content is used.

### Committee pack  (route: `/quality/reports/committee-pack`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Assemble executive committee material. Persona: quality manager/MS/CEO. Trace: `P-QOS-14`.
- **Entry points and exits:** Quality reports.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Committee pack — Sep 2026                                                │
│ [✓] Executive summary  [✓] Trend charts  [✓] CAPA  [✓] Data quality     │
│ [Generate pack]                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Checkbox list stacks.
- **Components:** Checkbox, Card, Button, RunChart, BarChart, CapaTimeline.
- **Data and API:** GET snapshots/alerts/CAPA; background generation; no websocket.
- **Fields and validation:** At least one section and period required.
- **States:** Draft selection, generating, ready, read-only.
- **Interactions and keyboard:** Space toggles; Enter generates.
- **Accessibility and localisation notes:** Charts/text summaries included in print.
- **Acceptance criteria:**
  - Given trend charts and CAPA selected; When Generate succeeds; Then both sections appear.
  - Given no section selected; When Generate is activated; Then submission is blocked.
  - Given locked period; When preview opens; Then locked status is shown.

### Quality profile and applicability  (route: `/admin/quality-profile`, module: `src/modules/quality-os`, release: R3)
- **Purpose and persona:** Enable NQAS District Hospital, NABH 6th Edition or both and apply configured scopes. Persona: tenant admin/quality manager. Trace: `P-QOS-9/10`, `TEN-009`, `QOS-005/006`.
- **Entry points and exits:** Administration/Quality. Exits: catalogue.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Quality profile                                                             │
│ [✓] NQAS — District Hospital       [✓] NABH — 6th Edition                 │
│ Scope: [Hospital-wide] [Departments] [Specialties]                         │
│ Enabled indicators 366 / 406                                [Save profile]│
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Scope controls stack.
- **Components:** Form, Checkbox, Select, Progress, DataTable, Badge, Button.
- **Data and API:** GET/PATCH tenant quality profile; no websocket.
- **Fields and validation:** NQAS/NABH booleans; applicable scope selections; no direct editing of source definitions.
- **States:** NQAS only, NABH only, both, none, scope conflict, unsaved.
- **Interactions and keyboard:** Save requires confirmation because enablement changes dashboard population.
- **Accessibility and localisation notes:** Enabled vs applicable vs framework-defined are separate labels.
- **Acceptance criteria:**
  - Given NQAS enabled; When profile saves; Then applicable NQAS indicators become enabled/available for configuration.
  - Given both enabled; When a shared semantic computation exists; Then it is not duplicated.
  - Given source definition edit is attempted; When control is activated; Then it remains unavailable.

### Catalogue governance — import  (route: `/platform/quality/catalogue`, module: `src/modules/platform`, release: R3)
- **Purpose and persona:** Import/version source packages, validate gates and publish new definitions without overwriting history. Persona: platform admin. Trace: `P-QOS-13`, `QOS-001/007/008/012`.
- **Entry points and exits:** Platform Quality navigation. Exits: validation/history/publish.
- **Layout:**
```text
┌────────────────────────────────────────────────────────────────────────────┐
│ Catalogue governance                                                      │
│ Current v0.2  NQAS 356  NABH 50  SHA-256 <hash>                           │
│ [Upload package] [Validate] [History]                                     │
│ Gates: 356 NQAS • 30+326 • 18 sheets • 50 NABH • 32+18                    │
└────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Gate results stack.
- **Components:** Card, Progress, Table, Alert, Badge, Button, Sheet.
- **Data and API:** GET source history; upload package; Celery validation with **5 s** status polling; publish mutation; no websocket.
- **Fields and validation:** Source file required; edition/version required; SHA-256 calculated/read-only; publish requires validation gates.
- **States:** Upload pending, validation running, hard-gate fail, pass, licensing warning, publish confirmation.
- **Interactions and keyboard:** No publish shortcut bypassing approval.
- **Accessibility and localisation notes:** Gate states have text.
- **Acceptance criteria:**
  - Given a valid baseline package; When Validate completes; Then 356 NQAS, 50 NABH, 30+326, 18 sheets and 32+18 checks are shown.
  - Given a hard gate fails; When Publish is attempted; Then Publish is blocked.
  - Given candidate v0.3 is published; When history opens; Then v0.2 remains available and reproducible.

### Catalogue import validation detail  (route: `/platform/quality/catalogue/validate`, module: `src/modules/platform`, release: R3)
- **Purpose and persona:** Inspect row-level/schema/provenance validation before publication. Persona: platform admin/reviewer. Trace: `P-QOS-13`, `QOS-012`.
- **Entry points and exits:** Catalogue governance. Exits: correction/publish.
- **Layout:**
```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Validation — candidate v0.3                                                │
│ PASS 356 NQAS | PASS 50 NABH | FAIL 0 framework | WARN metadata missing     │
│ Row | Field | Severity | Message | Locator                                 │
└──────────────────────────────────────────────────────────────────────────────┘
```
Tablet/variant notes: Validation rows use expandable detail.
- **Components:** DataTable, Badge, Alert, Accordion, Button.
- **Data and API:** GET validation result; job poll **5 s**; no websocket.
- **Fields and validation:** Reviewer comment conditional for allowed override.
- **States:** Pass, warning, fail, overridden-with-reason.
- **Interactions and keyboard:** `o` opens reviewer comment.
- **Accessibility and localisation notes:** Missing metadata and invalid source content are distinct labels.
- **Acceptance criteria:**
  - Given a hard validation failure; When the validation page loads; Then Publish remains disabled.
  - Given a warning only under an approved policy; When reviewer comment is entered; Then the warning is auditable as reviewed.
  - Given a malformed source row; When detail opens; Then exact source locator is shown.


## 10. Lighter coverage for R4-R7

R4-R7 reuse the R1-R3 shell, patient-context, forms, data tables, polling/realtime, permissions, audit, printing and accessibility rules. The screens below are implementation-entry specifications rather than full R1-R3 contracts. Release gating is configuration-driven; unavailable modules are hidden from users without permission, while a configured-but-not-yet-licensed capability may appear as `Not enabled` to administrators.

### LIS / Laboratory

**Route:** `/lis`; module `src/modules/lis`; R4. The worklist is department/facility scoped and shows order priority, patient banner, sample status and turnaround-time timestamps. Lab order data originates from OPD/IPD events; analyzer integration uses the facility bridge. No WebSocket is used for normal LIS workflow. Critical results use the persisted notification engine.

**Key screens:** `/lis/worklist`, `/lis/orders/:orderId`, `/lis/results/:resultId`, `/lis/critical-results`.

**UX risk:** a critical result must not disappear into a transient toast. The result remains persisted until acknowledged; acknowledgement records user/time and is visible in the audit trail. Any failed analyzer integration displays queued/retry state rather than silently converting the result to manual data.

**Acceptance:** Given a critical result, When the technician opens it, Then the critical state and acknowledgement control are visually distinct. Given the notification channel is unavailable, When the critical result is saved, Then the result remains available in the worklist and notification centre.

### RIS / Imaging

**Route:** `/ris`; module `src/modules/ris`; R4. Worklist columns: priority, patient, modality, order time, performed time, report status. Report detail provides a PACS launch control and report text. DICOM/PACS is an integration boundary; the UI does not expose raw DICOM transport details.

**Key screens:** `/ris/worklist`, `/ris/studies/:studyId`, `/ris/reports/:reportId`.

**UX risk:** report-finalisation and wrong-patient imaging association. PatientBanner is mandatory before opening or finalising a report; irreversible finalisation requires confirmation and records the actor.

### Pharmacy

**Route:** `/pharmacy`; module `src/modules/pharmacy`; R4. Dispensing worklist groups prescriptions by patient and encounter. Each item displays medicine, dose/frequency/duration, quantity, stock availability and substitution policy where configured.

**Key screens:** `/pharmacy/dispense`, `/pharmacy/prescriptions/:id`, `/pharmacy/stock`, `/pharmacy/stock-outs`.

**UX risk:** look-alike/sound-alike medicines and stock errors. Product name, strength, dosage form and quantity are shown together. Stock deduction is confirmed by the server before the dispense status becomes `Dispensed`.

### Blood Bank

**Route:** `/blood-bank`; module `src/modules/blood_bank`; R4. Requisition, component, cross-match and issue workflows use persistent patient and blood-unit context banners.

**Key screens:** `/blood-bank/donors`, `/blood-bank/collections`, `/blood-bank/inventory`, `/blood-bank/requisitions`, `/blood-bank/cross-match`, `/blood-bank/issue`, `/blood-bank/reactions`.

**UX risk:** patient/unit mismatch. Cross-match and issue screens require independent confirmation of patient identity, component/unit identifier and compatibility result; issue cannot be completed from a stale cached record. High-risk fields are grouped in a dedicated `Safety confirmation` section.

### Emergency

**Route:** `/emergency`; module `src/modules/emergency`; R5. The tracking board uses REST polling every **5 seconds** with visible `Last updated` and a stale warning at **15 seconds**. No WebSocket is used. Triage and assessment details open in a patient-context drawer/page.

**Key screens:** `/emergency/board`, `/emergency/patients/:id/triage`.

**UX risk:** stale tracking information. Stale state is explicit and cannot be mistaken for live state; browser focus loss does not stop polling when the board is in foreground mode.

### ICU and live vitals

**Route:** `/icu`; module `src/modules/icu`; R5. The flowsheet is normal REST/PWA workflow. The live-vitals dashboard is the sole clinical dashboard allowed to use Django Channels.

**Key screens:** `/icu/flowsheets`, `/icu/live-vitals`.

**Realtime:** WebSocket subscription is tenant/facility/ward/patient scoped. Show `Connected`, `Reconnecting`, or `REST fallback`. On socket loss, TanStack Query refetches persisted vitals every **5 seconds**; stale after **15 seconds**. The persisted clinical store remains authoritative.

**UX risk:** clinicians interpreting an old value as current. Every vital tile shows timestamp and source status. A disconnected dashboard displays a full-width `Live connection unavailable — showing persisted data` banner.

### OT

**Route:** `/ot`; module `src/modules/ot`; R5. Theatre schedule uses server-side time-slot conflict detection and clear pre-operative checklist progress.

**Key screens:** `/ot/schedule`, `/ot/cases/:caseId`, `/ot/cases/:caseId/anaesthesia`, `/ot/cases/:caseId/operative-note`.

**UX risk:** scheduling collision and incomplete safety checklist. Conflicts block booking; checklist omissions are inline, not discovered only at final submission.

### Claims / TPA / PM-JAY

**Route:** `/billing/claims`; module `src/modules/billing_insurance`; R6. Claims screens reuse Billing DataTable, evidence attachment, status pills and audit drawer. External adjudication remains out of scope; display only the HMIS-side submission/pre-authorisation state.

**Key screens:** `/billing/claims`, `/billing/claims/:claimId`, `/billing/preauth/:id`.

**UX risk:** duplicate submission. Submission controls display request state and disable repeated submission until an idempotent response is known.

### ABDM health-record exchange

**Route:** `/abdm/exchange`; module `src/modules/abdm_gateway`; R6. Consent-first flow; source/target context and purpose are visible before any share action. Facility-controlled UI only; screens inside an external ABDM app are not specified.

### NQAS/NABH self-assessment and exports

**Routes:** `/quality/assessments` and `/quality/exports`; R7. Reuse DataTable, EvidenceUploader, provenance badges, period lock, report preview and audit trail. Assessment score/evidence UI follows the source-specific assessment requirements introduced in R7; exact government export templates remain an open issue.

---

## 11. Government vs private configuration in the UI

Government and private behaviour is configuration, not separate frontend branches. The tenant profile contains accreditation profile, billing mode, category/scheme options, reporting configuration, facility type and enabled modules. The same routes render different fields and defaults based on configuration.

| Area | Government default | Private default | UI mechanism |
|---|---|---|---|
| Registration | Scan and Share + counter/token/OP slip | Scan and Share or counter; optional registration payment | Tenant policy controls visible fields |
| Billing | Free/scheme-covered services and category tracking | Tariff-based charges and insurance context | `billingMode` and service coverage flags |
| Quality | NQAS District Hospital | NABH 6th Edition | Framework profile and applicability resolver |
| Reporting | Quality-chain oriented reports | Internal committee / assessor evidence | Report template registry |
| Department scope | Configured public hospital departments/services | Configured private hospital specialties/services | Shared department configuration |

Both profiles may be enabled on the same tenant. When two definitions are semantically equivalent in numerator, denominator/population, unit, frequency, applicability and definition semantics, the UI shows one shared computation with both provenance references; otherwise it shows separate source-specific values. This prevents a generic formula from collapsing distinct NQAS/NABH definitions.

Design decision: all tenant configuration is stored and displayed as effective-dated policy objects so a locked Quality OS period can retain the configuration that produced it.

---

## 12. Accessibility and inclusive design

Core workflows target WCAG 2.1 AA. Accessibility is part of the component contract, not a final visual audit.

### 12.1 Concrete accessibility checklist

| Requirement | Concrete rule | Primary screens |
|---|---|---|
| Keyboard access | Every actionable control reachable by Tab; logical visual order | All R1-R3 |
| Focus visibility | 2px equivalent visible focus indicator with >= 3:1 contrast against adjacent colours | All |
| Labels | Every input has a persistent programmatic label; helper text is linked | Forms |
| Icon-only buttons | Every icon-only `Button` has an explicit accessible name | All |
| Status | Do not encode status using colour alone; pair colour with text, marker or pattern | Quality, registration, clinical |
| Tables | Header associations, keyboard row actions, server-side pagination | Registry, billing, Quality OS |
| Dialogs | Focus trap, labelled title, Escape closes only non-destructive dialogs | Merge, break-glass, lock |
| Errors | Inline error text plus programmatic association; focus first invalid control on blocked submit | Forms |
| Motion | Respect `prefers-reduced-motion`; replace animated transitions with immediate state changes | All |
| Scaling | No loss of primary workflow at 200% text zoom | All core workflows |
| Touch | Minimum 44x44 CSS px target on tablet | Ward, IPD, ICU |
| Long text | Text wraps; never truncate clinical values without an explicit expansion control | EMR, Quality detail |

### 12.2 Contrast verification

The following intended text/background pairs meet WCAG 2.1 AA for normal text (minimum 4.5:1) and are the approved semantic pairings:

| Pair | Foreground | Background | Contrast ratio | Use |
|---|---|---|---:|---|
| Primary action | `#ffffff` | `#0f766e` | 5.47:1 | Primary buttons |
| Critical | `#ffffff` | `#b91c1c` | 6.47:1 | Critical alert/status |
| Warning | `#ffffff` | `#a16207` | 4.92:1 | Warning/status |
| Success | `#ffffff` | `#15803d` | 5.02:1 | Success/status |
| Info | `#ffffff` | `#1d4ed8` | 6.70:1 | Informational status |
| Unsynced | `#ffffff` | `#7c3aed` | 5.70:1 | Sync status |
| Provisional | `#ffffff` | `#6b7280` | 4.83:1 | Provisional badge |
| Locked | `#ffffff` | `#334155` | 10.35:1 | Locked badge |
| Primary text | `#0f172a` | `#ffffff` | 17.85:1 | Light body text |
| Secondary text | `#475569` | `#ffffff` | 7.58:1 | Light supporting text |
| Dark primary text | `#f8fafc` | `#0f172a` | 17.06:1 | Dark body text |

Design decision: status fills use the tested white-on-dark pairings above. Do not create new semantic status colours without a contrast check.

### 12.3 Keyboard-only walkthroughs

**Returning registration:** `Ctrl+K` patient search → type query → ArrowDown/Enter patient → `n` new encounter → department Select → `Enter` confirm → print action. The test measure is total keyboard interaction under 30 seconds for a returning patient, consistent with NFR-USE-001.

**Discharge:** open admission → `d` discharge → Tab through mandatory disposition → summary fields → save draft → finalise. Attempting finalise with missing disposition must focus the disposition control and leave the discharge incomplete.

**Monthly quality cycle:** open Quality → filter period/framework → resolve DQ exceptions → open alert → raise CAPA → close period. No step requires a pointer device.

### 12.4 Screen-reader rules

Use semantic headings in route order, table headers with scope, fieldset/legend for grouped safety fields, `aria-describedby` for helper/error content, and `aria-live="polite"` for non-critical refresh messages. Critical alerts use assertive announcements only when the event requires immediate user attention and are also persisted in the notification centre.

---

## 13. Localisation and content design

All UI strings are externalised from React components. Components receive translated strings rather than hard-coded English labels. Do not concatenate translated fragments; use complete message templates with named interpolation variables.

### 13.1 Preferred terminology

| Preferred term | Avoid / clarify |
|---|---|
| UHID | Patient ID as the only label |
| ABHA | “Health ID” without the ABHA term |
| OP slip | Receipt, when it is clinically the OP slip |
| LAMA | “Left hospital” in system labels |
| Disposition | “Discharge type” when the structured field is the source term |
| Patient | Case, when referring to the person |
| Encounter | Visit, when the domain object is the encounter |
| Ward in-charge | Ward manager, unless customer wording requires otherwise |
| Quality OS | Quality dashboard, when referring specifically to the product module |

### 13.2 Content rules

Use action + object + outcome where space permits. Error messages state what happened, what the user can do, and whether data was saved.

| Before | After |
|---|---|
| `Something went wrong.` | `The patient was not saved. Check the highlighted fields and try again.` |
| `Invalid.` | `Enter a valid mobile number.` |
| `Error saving.` | `The change was not saved. No clinical data was marked as complete.` |
| `No data.` | `No indicator value is available for this period because the required input is missing.` |
| `Connection error.` | `Connection lost. Showing the last confirmed data. Changes entered offline are marked Unsynced.` |

### 13.3 Indian formats

Design decision: use locale-aware Indian formatting with configurable formatters. Default examples are `02 Oct 2026` for human-readable dates, `2,50,000` for Indian grouping, and `₹2,50,000.00` for INR. Clinical timestamps may use `24-hour` time for unambiguous event ordering. The formatter must remain locale-driven so final language/customer conventions can be configured without changing component code.

### 13.4 Hindi and Mizo

Hindi requires Devanagari-capable font fallback and approximately 15% additional line-height where labels wrap. Mizo uses Latin script but may require local terminology and longer labels. Layouts reserve at least 30% horizontal expansion for translated strings before truncation is permitted. RTL is not required by the current requirement set.

Patient-facing OP slips, QR posters, receipts and notices use a print-language selection from the configured tenant template. The product does not design the patient-facing screens inside the ABDM application.

---

## 14. Responsive and device behaviour

### 14.1 Layout targets

| Viewport | Grid | Density | Behaviour |
|---|---:|---|---|
| 1366x768 | 12 columns | Comfortable default | Baseline supported workstation |
| 1920x1080 | 12 columns | Comfortable | More columns/tables visible; no larger base text required |
| Tablet landscape ~1024x768 | 8 columns | Compact where data-entry heavy | Sidebar collapses to Sheet; touch targets remain >=44px |
| Tablet portrait ~768x1024 | 4 columns | Compact | Tables become horizontally scrollable or use stacked row detail; primary action remains visible |
| Kiosk 1920x1080+ | Full-screen | Display | No authenticated shell; large token typography and high contrast |

Tailwind breakpoints use `sm`, `md`, `lg`, and `xl`; do not implement Ant Design grid props. Desktop pages use a max content width only where it prevents excessive line length; operational data tables may use the full available width.

### 14.2 Mobile boundary

Phones are not a supported HMIS workstation form factor for v1. The facility-controlled patient-facing path is the QR poster/counter display/OP slip; the external ABDM application owns its mobile UI. The HMIS must not silently transform clinical screens into a phone UX that changes safety-critical ordering or disposition behaviour.

### 14.3 Tablet interaction

Sticky patient identity and primary action bars are permitted only when they do not cover content. Sheets replace side-by-side secondary panels in portrait mode. No modal-on-modal interaction is allowed.

### 14.4 Kiosk

The kiosk route occupies the viewport, hides browser-oriented navigation, uses large type, and shows facility/counter identity plus token status. REST polling is every **3 seconds**; `Last updated` is always visible. After a network interruption, the board retries automatically. It never uses Django Channels and never allows editing or patient lookup.


## 15. Performance and perceived-performance budget for the UI

The UI is designed against the SRS performance targets; where the SRS identifies a target as proposed/TBD, the UI requirement below is an implementation budget rather than a claim of measured production performance.

### 15.1 Route and bundle behaviour

- The authenticated shell and route chrome load first; each module under `src/modules/` is lazy-loaded with route-level code splitting.
- Patient registration, OPD, IPD and Quality OS receive separate route chunks so a user entering registration does not download diagnostics, ICU or OT code.
- TanStack Query caches server state by tenant, facility and route scope. Cached data may populate the shell while a refetch updates the page, but stale clinical state must be visibly labelled when relevant.
- Skeletons appear when a request is expected to exceed **120 ms**. A skeleton preserves the final layout dimensions to minimise layout shift.

### 15.2 Interaction budgets

| Interaction | UI budget | Behaviour |
|---|---:|---|
| Patient search | <=1.0 s result target | Debounce 150 ms after 2+ characters; server-side search |
| Common read | <=300 ms API target | Show prior cached result while refetching when safe |
| Quality dashboard | <=3.0 s from snapshot target | Load cards first, charts second if necessary |
| Returning registration | <30 s keyboard interaction | Measured task success, not network latency alone |
| Kiosk refresh | 3 s poll | Always show `Last updated` |
| Bed/census refresh | 5 s poll | Poll while foreground; show stale state after 15 s |
| Emergency board | 5 s poll | Show stale state after 15 s |
| Live vitals fallback | 5 s REST refetch | Active only when WebSocket unavailable |

### 15.3 Optimism rules

Optimistic UI is allowed only for non-clinical preferences or reversible local presentation state. It is prohibited for clinical orders, prescriptions, patient merge, bed allocation, admission, discharge finalisation, billing payment, result finalisation, blood issue, period lock, catalogue publish and any action whose persisted outcome affects patient care or accreditation evidence.

A clinical order has states `Draft` → `Submitting` → `Server confirmed` or `Save failed`. The UI must never display `Saved` before the server response. This implements UI-007/NFR-USE-003.

### 15.4 Tables and charts

All Quality OS tables use server-side pagination and filtering. Design decision: virtualised row rendering is introduced when a table would otherwise render more than **100 visible records** in one route. Row actions remain keyboard reachable.

Charts render the selected period at up to **60 points** without special handling and downsample larger series to a maximum of **200 plotted points**. The underlying data is always available through a tabular toggle. A chart must not become the only representation of a regulated indicator value.

SVG charts use a fixed minimum drawing height of 220 px for desktop cards and 180 px on tablet. Text labels are kept outside the plotting region where possible to avoid overlap. Expensive SVG nodes such as markers are limited by data-point count rather than hidden behind CSS.

### 15.5 Failure and degraded performance

When a request exceeds the normal UI budget, the interface does not block all navigation. Route-local loading continues in place, stale timestamps remain visible, and retry actions are attached to the affected section. A stale value is never restyled as current merely because rendering completed.

---

## 16. Open questions, assumptions and risks

The following items remain unresolved in the source documents or require confirmation before a final UI contract is frozen. The screens use the recommended default only as a documented working assumption.

| ID | Open issue / evidence | Affected screens | Recommended default | Risk |
|---|---|---|---|---|
| OQ-01 | Future NQAS workbook source/version/hash governance is not fully defined | Catalogue governance, indicator detail, imports | Require source file, SHA-256 hash, source date, reviewer and import timestamp before publish | High |
| OQ-02 | NABH 6th Edition text/licensing for customer-facing reproduction is unresolved | Indicator detail, catalogue, reports/exports | Show concise source metadata and controlled excerpts only until licensing is confirmed | High |
| OQ-03 | Exact government reporting formats/state portals are unspecified | Quality reports, exports | Ship a configurable CSV/XLSX-style export contract first; keep final state templates configurable | High |
| OQ-04 | Functional-bed denominator method is unresolved where occupancy/turnover interpretation is ambiguous | Facility setup, IPD census, Quality indicator detail | Preserve source definition verbatim and force a tenant-level denominator policy before period lock | High |
| OQ-05 | Patient-facing languages are not final | QR flow, OP slip, kiosk-adjacent patient material, receipts | English default; externalised strings; add Hindi/Mizo template packs without changing workflow structure | Medium |
| OQ-06 | Exact offline ward workflow boundary is open | IPD ward screens, nursing forms | Limit queue to explicitly approved short-lived ward entries; never queue an apparently completed clinical order | High |
| OQ-07 | Overnight indicator compute window is TBD | Quality home, month-end close | Display calculation timestamp and `Last calculation`; block close while required calculations are pending | Medium |
| OQ-08 | Long-term audit/clinical/quality retention periods are TBD | Audit, Quality OS, CAPA | Render retention as tenant policy metadata; do not auto-delete from UI without policy enforcement | High |
| OQ-09 | R3 catalogue JSON has null `type`, `direction`, `calculation_mode`, and blank `department_or_specialty` values despite the required catalogue model | Indicator catalogue/detail/manual forms | UI supports these fields but displays `Not populated in source baseline` until populated through the normative specification/import validation | High |
| OQ-10 | NQAS units are not consistently populated in the JSON representation | Catalogue, indicator detail, chart axis | Derive display unit from the active definition specification, never infer `%` from a formula string | High |
| OQ-11 | R1 setup asks for initial indicator inputs while full Quality OS is R3 | Facility setup | Collect only baseline inputs explicitly required by enabled source definitions and mark them as onboarding data | Medium |
| OQ-12 | Both NQAS and NABH can be enabled on one tenant, but semantic equivalence rules need operational governance | Quality home, indicator detail | Calculate once only after a semantic-equivalence check; otherwise preserve separate source values | High |
| OQ-13 | Realtime scaling thresholds for Notifications/Live Vitals are not final | Notification centre, R5 live vitals | Keep one reconnect/fallback UX; make threshold configuration operational rather than a screen-level dependency | Medium |
| OQ-14 | Exact selection of first TPAs/schemes is a later-release concern | R6 claims | Keep payer controls generic and configuration-driven | Low |

### 16.1 Catalogue-specific verification note

The supplied machine-readable catalogue is suitable as the import representation but should not be treated as the sole source for UI typing. The source specification says every indicator should preserve framework, edition, scope, type/dimension, unit, direction, frequency, numerator, denominator, formula/operator, source-of-data, applicability and definition version. The design therefore supports all those fields while explicitly displaying incomplete source metadata as incomplete rather than manufacturing values.

### 16.2 Design assumptions used to proceed

The UI uses the source-defined statuses `draft`, `provisional`, `locked`, `superseded` and `not_applicable`; DQ flags remain separate from value status. A locked value can only be corrected through a versioned correction workflow. Any recommendation in this section is a product design decision, not a change to the normative NQAS/NABH source.

---

## 17. Traceability matrix

Every R1-R3 PRD Must story is mapped below to at least one screen and an SRS requirement. The screen specifications also contain the same IDs locally so engineering can trace the requirement without opening this table.

### 17.1 PRD Must stories → screens → SRS

| PRD story | Release | Screen(s) | SRS trace |
|---|---|---|---|
| P-REG-1 | R1 | Patient registry | REG-001, REG-002; UI-002; NFR-USE-001 |
| P-REG-2 | R1 | Patient registry; Duplicate review | REG-003 |
| P-REG-3 | R1 | QR poster; Awaiting verification; Verification | ABD-001–010 |
| P-REG-4 | R1 | Awaiting verification; Verification | REG-006; ABD-009 |
| P-REG-5 | R1 | QR management; QR poster | ABD-001, ABD-002 |
| P-REG-6 | R1 | Counter token kiosk; OP slip | REG-010, REG-011; UI-003 |
| P-REG-9 | R1 | Patient registry; Registration configuration | REG-012 |
| P-RT-1 | R1 | Notification centre | PLT-001; INT-012 |
| P-RT-4 | R1-R2 | Counter kiosk; Bed board; Emergency board pattern | PLT-003, PLT-008; INT-013 |
| P-ADM-1 | R1 | Users; Roles; Departments; Wards & beds | TEN-004, TEN-008 |
| P-ADM-3 | R1 | Audit log; Patient access history | AUD-001–004 |
| P-ADM-5 | R1 | Platform hospital onboarding | TEN-010 |
| P-SET-1 | R1 | Facility setup wizard | SET-001–008 |
| P-SET-2 | R1 | Configuration history; setup editing | SET-009–012 |
| P-OPD-1 | R2 | OPD dashboard; Doctor consultation | OPD-001, OPD-007 |
| P-OPD-2 | R2 | Doctor consultation | OPD-005, OPD-008 |
| P-IPD-1 | R2 | IPD admission; Bed board | IPD-001–003, IPD-012 |
| P-IPD-2 | R2 | Bed board; Midnight census | IPD-003, IPD-005 |
| P-IPD-3 | R2 | Discharge | IPD-006 |
| P-IPD-4 | R2 | Discharge summary | IPD-007 |
| P-IPD-5 | R2 | IPD admission | IPD-001, IPD-012 |
| P-IPD-6 | R2 | Transfer | IPD-004, IPD-013 |
| P-EMR-1 | R2 | EMR longitudinal record | EMR-001–005 |
| P-BIL-1 | R2 | Tariffs; Billing | BIL-001 |
| P-BIL-2 | R2 | Billing; Payment/receipt | BIL-002 |
| P-BIL-4 | R2 | Government scheme/free service | BIL-003 |
| P-QOS-1 | R3 | Quality home; Indicator catalogue | QOS-001, QOS-009, QOS-010 |
| P-QOS-2 | R3 | Indicator detail; Drill-through | QOS-051 |
| P-QOS-3 | R3 | Indicator detail; Trends | QOS-060, QOS-061 |
| P-QOS-4 | R3 | Alerts; Indicator detail | QOS-062 |
| P-QOS-5 | R3 | CAPA list/board/detail | QOS-070–072 |
| P-QOS-6 | R3 | Period close; Reproduction | QOS-053, QOS-054 |
| P-QOS-7 | R3 | Data-quality centre | QOS-050 |
| P-QOS-8 | R3 | Indicator catalogue | QOS-005, QOS-006; catalogue requirements |
| P-QOS-9 | R3 | Quality profile/applicability | TEN-009; QOS-005, QOS-006, QOS-009 |
| P-QOS-10 | R3 | Quality profile/applicability | TEN-009; QOS-040–045 |
| P-QOS-11 | R3 | Manual indicator entry | QOS-003, QOS-021, QOS-044 |
| P-QOS-12 | R3 | Sampling plans; Indicator detail/evidence | QOS-004, QOS-051 |
| P-QOS-13 | R3 | Catalogue governance; Validation | QOS-007, QOS-008, QOS-012 |
| P-QOS-19 | R3 | Indicator detail; Catalogue | QOS-002, QOS-003, QOS-008 |
| P-QOS-20 | R3 | Indicator detail | QOS-002, QOS-008 |

### 17.2 R1-R3 requirement coverage

| SRS requirement family | Covered screens |
|---|---|
| UI-001/UI-002/UI-003/UI-004/UI-005/UI-006/UI-007 | Global shell; Registration; Kiosk; Core clinical; Quality OS; Printing patterns |
| INT-001/INT-011 | All authenticated and admin routes via typed OpenAPI REST client |
| INT-012/PLT-001 | Notification centre |
| INT-013/PLT-003 | Kiosk, bed board, census, operational queues |
| INT-014/PLT-004 | Background state surfaces and job status where exposed |
| TEN-001–011 | Sign-in, tenant selection, onboarding, admin configuration, quality profile |
| SET-001–013 | Facility setup, configuration history, users/departments/wards/beds |
| REG-001–013 / ABD-001–017 | Patient registry, QR management, self-registration queue, verification, kiosk, OP slip |
| OPD-001–008 | OPD dashboard and consultation |
| IPD-001–013 | Admission, bed board, census, transfer, discharge, summary |
| EMR-001–006 | Longitudinal EMR |
| BIL-001–006 | Tariffs, billing, payment, scheme coverage |
| QOS-001–074 | Quality OS R3 screens |
| AUD-001–004 | Audit log and access-history views |
| NFR-USE-001–003 | Registration timing, accessibility, error/offline patterns |
| NFR-REL-001–005 | Append/versioned clinical screens, lock/reproduce, offline/realtime safeguards |

---

## 18. Appendix

### 18.1 Usability test plan

| Flow | Task | Success criterion | Primary measure | Secondary measure |
|---|---|---|---|---|
| Returning-patient registration | Find existing UHID, select department, issue token, print OP slip | Complete without pointer assistance and without duplicate creation | Keyboard interaction time; target <30 s | Error count; duplicate-warning comprehension |
| ABHA QR self-registration | Scan facility QR; share profile; clerk verifies; token appears | Exactly one patient/intake created; correct department/token; provisional handling works when matching is ambiguous | End-to-end completion rate | Time in verification queue; incorrect-match rate |
| Discharge with disposition | Open admission, complete mandatory disposition, create summary, finalise | Cannot finalise without disposition; correct disposition persists | Task completion rate | Invalid-submit recovery time; wrong-patient incidents |
| Monthly quality cycle | Review dashboard, fix DQ item, inspect alert, create CAPA, close period | User can trace value → source → action and lock only when required inputs are valid | Time to monthly pack | Traceability errors; lock/reproduction success |
| CAPA raise-to-close | Raise, assign owner, record RCA/actions/evidence, verify, close or reopen | All required CAPA states and evidence transitions are understandable and auditable | Successful state-transition rate | Time per transition; reopen comprehension |

Test participants should include registration clerks, doctors, nurses/ward in-charge staff, quality managers and administrators as applicable to each workflow. The SRS explicitly calls for task-based usability testing with registration clerks, nurses and quality managers.

### 18.2 Screen inventory

R1-R3 are listed at full route granularity; R4-R7 entries are the lighter screen set. A screen is included only when it has a requirement/story relationship or is a required interaction surface from the product brief.

| Route | Module | Persona | Release | Priority |
|---|---|---|---|---|
| `/auth/sign-in` | auth | All users | R1 | Must |
| `/auth/sso` | auth | Group/tenant admin | R1 | Should |
| `/auth/mfa` | auth | Privileged users | R1 | Must |
| `/select-tenant` | identity-tenancy | Multi-tenant users | R1 | Must |
| `/platform/tenants/new` | platform | Platform admin | R1 | Must |
| `/admin/setup` | identity-tenancy | Tenant admin | R1 | Must |
| `/admin/configuration/history` | identity-tenancy | Tenant admin | R1 | Must |
| `/admin/users` | identity-tenancy | Tenant admin | R1 | Must |
| `/admin/roles` | identity-tenancy | Tenant admin | R1 | Must |
| `/admin/departments` | identity-tenancy | Tenant admin | R1 | Must |
| `/admin/wards-beds` | identity-tenancy | Tenant admin | R1 | Must |
| `/patients` | patient-registry | Registration clerk | R1 | Must |
| `/patients/duplicates/:id` | patient-registry | Registration clerk | R1 | Must |
| `/patients/merge` | patient-registry | Authorised admin | R1 | Must |
| `/patients/:uhid` | patient-registry | Clinician/admin | R1 | Must |
| `/patients/:uhid/abha` | patient-registry | Registration clerk | R1 | Should |
| `/admin/abdm/qr` | abdm-gateway | Tenant admin | R1 | Must |
| `/abdm/qr/:qrId/print` | abdm-gateway | Tenant admin | R1 | Must |
| `/registration/awaiting-verification` | abdm-gateway | Registration clerk | R1 | Must |
| `/registration/awaiting-verification/:id` | abdm-gateway | Registration clerk | R1 | Must |
| `/kiosk/tokens/:displayId` | patient-registry | Kiosk viewer | R1 | Must |
| `/print/op-slip/:visitId` | patient-registry | Registration clerk/patient | R1 | Must |
| `/admin/registration-config` | patient-registry | Tenant admin | R1 | Should |
| `/admin/audit` | audit | Compliance/admin | R1 | Must |
| `/patients/:uhid/audit` | audit | Compliance/admin | R1 | Must |
| `/patients/:uhid/break-glass` | audit | Clinician | R1 | Should |
| `/notifications` | platform | All authorised users | R1 | Must |
| `/opd` | opd | OPD doctor | R2 | Must |
| `/opd/consultation/:encounterId` | opd | OPD doctor | R2 | Must |
| `/ipd/admissions/new` | ipd | Nurse/doctor | R2 | Must |
| `/ipd/bed-board` | ipd | Ward in-charge | R2 | Must |
| `/ipd/census` | ipd | Ward in-charge | R2 | Must |
| `/ipd/transfers/new` | ipd | Ward in-charge | R2 | Must |
| `/ipd/discharge/:admissionId` | ipd | Doctor | R2 | Must |
| `/ipd/discharge/:id/summary` | ipd | Doctor | R2 | Must |
| `/emr/patients/:uhid` | emr | Clinician | R2 | Must |
| `/billing/tariffs` | billing-insurance | Billing/admin | R2 | Must |
| `/billing/encounters/:encounterId` | billing-insurance | Billing exec | R2 | Must |
| `/billing/payments/:invoiceId` | billing-insurance | Billing exec | R2 | Must |
| `/billing/scheme-coverage/:encounterId` | billing-insurance | Government billing/admin | R2 | Must |
| `/billing/scheme-coverage` | billing-insurance | Government billing/admin | R2 | Must |
| `/quality` | quality-os | Quality manager/MS | R3 | Must |
| `/quality/indicators` | quality-os | Quality manager | R3 | Must |
| `/quality/indicators/:id` | quality-os | Quality manager | R3 | Must |
| `/quality/indicators/NQAS-DH-001` | quality-os | Quality manager | R3 | Must |
| `/quality/indicators/NABH-ORG-001` | quality-os | Quality manager | R3 | Must |
| `/quality/indicators/:id/drill-through` | quality-os | Quality manager | R3 | Must |
| `/quality/manual/:id` | quality-os | Quality manager | R3 | Must |
| `/quality/sampling` | quality-os | Quality manager | R3 | Must |
| `/quality/data-quality` | quality-os | Quality manager | R3 | Must |
| `/quality/alerts` | quality-os | Quality manager | R3 | Must |
| `/quality/alerts/config` | quality-os | Quality manager/admin | R3 | Should |
| `/quality/capa` | quality-os | Quality manager | R3 | Must |
| `/quality/capa/board` | quality-os | Quality manager | R3 | Must |
| `/quality/capa/:id` | quality-os | Quality manager | R3 | Must |
| `/quality/period-close` | quality-os | Quality manager | R3 | Must |
| `/quality/period-close/:period/reproduce` | quality-os | Quality manager | R3 | Must |
| `/quality/reports/monthly` | quality-os | Quality manager | R3 | Should |
| `/quality/reports/committee-pack` | quality-os | Quality manager | R3 | Should |
| `/admin/quality-profile` | quality-os | Tenant admin | R3 | Must |
| `/platform/quality/catalogue` | platform | Platform admin | R3 | Must |
| `/platform/quality/catalogue/validate` | platform | Platform admin | R3 | Must |
| `/quality/indicators/:id/versions` | quality-os | Quality manager/platform reviewer | R3 | Must |
| `/lis/worklist` | lis | Lab technician | R4 | Must |
| `/lis/results/:resultId` | lis | Lab technician/doctor | R4 | Must |
| `/ris/worklist` | ris | Radiology tech | R4 | Should |
| `/ris/reports/:reportId` | ris | Radiologist/doctor | R4 | Should |
| `/pharmacy/dispense` | pharmacy | Pharmacist | R4 | Must |
| `/pharmacy/stock` | pharmacy | Pharmacist | R4 | Must |
| `/blood-bank/requisitions` | blood-bank | Blood bank tech/clinician | R4 | Must |
| `/blood-bank/cross-match` | blood-bank | Blood bank tech | R4 | Must |
| `/blood-bank/issue` | blood-bank | Blood bank tech | R4 | Must |
| `/emergency/board` | emergency | ER nurse | R5 | Must |
| `/emergency/patients/:id/triage` | emergency | ER nurse | R5 | Must |
| `/icu/flowsheets` | icu | ICU nurse | R5 | Must |
| `/icu/live-vitals` | icu | ICU/ward clinician | R5 | Must |
| `/ot/schedule` | ot | OT coordinator | R5 | Must |
| `/ot/cases/:caseId` | ot | OT coordinator/clinician | R5 | Must |
| `/billing/claims` | billing-insurance | Billing/TPA exec | R6 | Should |
| `/billing/preauth/:id` | billing-insurance | Billing/TPA exec | R6 | Should |
| `/abdm/exchange` | abdm-gateway | Authorised clinician/admin | R6 | Should |
| `/quality/assessments` | quality-os | Quality manager | R7 | Should |
| `/quality/exports` | quality-os | Quality manager | R7 | Should |

### 18.3 Implementation handoff notes

1. Route names use the `src/modules/<bounded_context>/...` convention and should mirror backend bounded contexts. The router must preserve tenant/facility context on deep links.
2. Patient-context tabs live in Zustand; server state lives in TanStack Query; forms use React Hook Form + Zod.
3. Any new clinical screen must reuse PatientBanner and must define wrong-patient and permission states before it is accepted.
4. Any new operational dashboard must define its polling interval, `Last updated`, stale threshold and REST retry behaviour.
5. Any new realtime screen requires architecture review; only notifications and live vitals may use Django Channels.
6. Any new Quality OS indicator screen must render the source unit/operator as supplied. A percentage-looking card is not acceptable when the source definition is a count, rate, ratio, time or median.

### 18.4 Completion summary

- Produced: `UI/UX_design.md`, version 0.1 draft, for review.
- Coverage: R1 Foundation, R2 Core Clinical and R3 Quality OS v1 are specified at screen-contract level; R4-R7 are covered with reusable patterns and key screens.
- Quality OS baseline: 406 source definitions, consisting of 356 NQAS and 50 NABH KPIs.
- Safety-critical flows covered: identity/duplicate prevention, break-glass, offline save confirmation, discharge disposition, period locking and reproducibility, CAPA evidence.
- Required UI constraints respected: Vite/React, Shadcn/Tailwind, lucide-react, inline SVG, TanStack Query, RHF/Zod, Zustand, restricted Channels usage.
- Highest-priority unresolved items: source/licensing governance, government export formats, functional-bed denominator method, patient-facing languages and catalogue metadata completeness.
- The supplied JSON was inspected for real field/value shape; several requested typed metadata fields are currently unpopulated and are therefore treated as source-data gaps rather than invented UI values.
- Final implementation acceptance should run the Section 18 usability flows and the Section 17 traceability checks before declaring R1-R3 design complete.
