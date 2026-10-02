# SaaS HMIS: Product Requirements Document (PRD)

**Version:** 0.5 (draft) | **Status:** For review | **Date:** 1 Oct 2026

**Quality OS source baseline:** 356 NQAS District Hospital indicators from the supplied workbook and 50 NABH 6th Edition KPIs from the supplied standard; **canonical total = 406.** See `SaaS HMIS Quality OS Indicator Specification v0.2.md` and the machine-readable `SaaS HMIS Quality OS Indicator Catalog v0.2.json`. **Derived from:** Architecture Document v0.6 | **Companion:** Software Requirements Specification (SRS) v0.5 **Changes from v0.1/v0.2:** generic cross-framework discharge-rate starter KPI dropped; source-specific NQAS Discharge Rate indicators from the supplied workbook are retained; bed-days from the midnight census; NQAS limited to District Hospital level for now; backend changed to Django + Django REST Framework with Celery/Celery Beat; **Django Channels is restricted strictly to realtime notifications and live vitals dashboards**; **frontend changed from Ant Design 5 to Shadcn UI on Tailwind CSS v4 with inline SVG charts.**

> Targets, prices and market figures in this document are **hypotheses to validate**, not facts.

---

## 1. Product Overview

### 1.1 Summary

A cloud-based, multi-tenant **Hospital Management Information System (HMIS)** for government and private hospitals in India, averaging \~100 beds, covering registration, OPD, IPD, emergency, ICU, OT, laboratory, imaging, pharmacy, **blood bank**, billing/insurance and clinical records, with a built-in **Quality OS** that calculates accreditation quality indicators automatically and manages corrective and preventive actions (CAPA).

### 1.2 Problem

- Small and mid-sized hospitals run disconnected tools or paper registers. Registration queues are long, data is re-entered, and bed and patient flow are invisible.
- Quality teams compile monthly indicators by hand from registers (bed occupancy, LAMA, length of stay, infection data). The work is slow, error-prone, and hard to defend to an assessor.
- Government hospitals work toward **NQAS**; private hospitals work toward **NABH**. The indicator sets, cadence and reporting differ, and most HMIS products support neither well.
- India's digital health programme (**ABDM/ABHA**) expects facilities to support patient identity and record exchange, including QR-based registration, which many systems lack or implement poorly.

### 1.3 Vision

One affordable, standards-aware platform where a hospital registers a patient in seconds, runs its clinical and administrative workflows digitally, and gets its quality indicators and improvement actions as a by-product of normal work.

### 1.4 Product principles

1. **Capture once, use everywhere.** Structured data entered in clinical workflows feeds billing, reporting and quality without re-keying.
2. **Quality by design.** Workflows capture the fields that accreditation indicators need (for example discharge disposition).
3. **India-first.** ABDM, DPDP, NQAS, NABH and Indian scheme workflows are first-class, not add-ons.
4. **Usable on a busy ward.** Fast data entry, minimal clicks, keyboard-friendly, resilient to brief connectivity loss.
5. **Safe by default.** Strict tenant isolation, role-based access, and complete audit trails.

### 1.5 Product architecture boundaries

- The core application API is a **Django + Django REST Framework modular monolith** running under ASGI.
- **Celery + Celery Beat** handle asynchronous/background processing such as indicator computation, reports, notifications, integrations and outbox dispatch.
- **Django Channels is deliberately narrow:** it is used only for the real-time notification engine and live vitals dashboards for authorised ICU/ward users.
- OPD token displays, bed boards, emergency boards and other non-vitals operational screens use normal REST APIs with polling/refetching rather than Channels.
- Realtime delivery is never the source of truth: notifications and clinical vitals remain persisted in the authoritative database.

## 2. Goals and Non-Goals

### 2.1 Goals

| # | Goal |
| --- | --- |
| G1 | Reduce patient registration time and OPD registration queues, including self-registration via ABHA QR |
| G2 | Give each hospital a single, complete electronic record per patient across departments |
| G3 | Automate calculation of core operational and accreditation indicators, with drill-through to source cases |
| G4 | Provide a closed-loop CAPA process tied to indicators |
| G5 | Serve both government (NQAS) and private (NABH) hospitals from one codebase through configuration |
| G6 | Meet ABDM, DPDP and tenant-isolation requirements well enough to pass hospital security reviews |
| G7 | Scale to hundreds of hospitals without per-hospital deployments |

### 2.2 Non-goals (v1)

- Native mobile apps, telemedicine video, patient-facing portal beyond ABHA-based sharing
- Payer-side systems and insurer claim adjudication
- Full ERP (HR, payroll, procurement) beyond what clinical and billing flows need
- NQAS facility levels other than District Hospital (CHC, PHC, urban PHC) in v1
- Automated clinical decision support or diagnosis

## 3. Target Customers

| Segment | Profile | Key needs | Accreditation focus |
| --- | --- | --- | --- |
| **Government hospitals** | District hospitals (the only government level supported for now; other levels later) | Free/low-cost OPD at scale, Scan and Share registration, scheme and category handling, NQAS indicators and reporting up the chain | NQAS |
| **Private hospitals** | Independent and small-group hospitals; \~50-300 beds | Billing and TPA/insurance, pharmacy and lab revenue, patient experience, NABH readiness | NABH |
| **Hospital groups** | Multi-facility private or public groups | Group-level dashboards, SSO, standardised configuration | Either or both |

Notes: NABH's hospital standards apply to organisations with more than 50 sanctioned inpatient beds, which suits the 100-bed target; smaller facilities may need different NABH programmes and are a later segment.

## 4. Users and Personas

| Persona | Setting | Top jobs to be done |
| --- | --- | --- |
| Registration clerk | OPD counter | Register or find a patient fast, issue token, collect fee |
| **Patient (self-registering)** | Phone, at the facility | Scan QR, share ABHA profile, get a token without queueing |
| OPD doctor | Consultation room | See queue, review history, record notes, prescribe, order tests |
| Nurse / ward in-charge | Ward, ICU | Admit, assess, chart vitals, give medication, hand over, discharge |
| Lab technician | Laboratory | Receive orders, collect samples, enter or auto-receive results, report critical values |
| Radiologist / technician | Imaging | Receive orders, record studies, report, view images |
| Pharmacist | Pharmacy | Dispense against prescriptions, manage stock, flag stock-outs |
| Billing / TPA executive | Billing desk | Create bills, handle insurance and scheme claims |
| Medical Superintendent / CEO | Admin | See occupancy, flow, revenue and quality at a glance |
| **Quality manager** | Quality cell | Get indicators, run trend analysis, manage CAPA, prepare for assessment |
| Tenant administrator | Hospital IT | Configure users, departments, beds, tariffs, QR codes, accreditation profile |
| Platform administrator | Vendor | Onboard hospitals, manage catalogue and support |

## 5. Product Scope by Module

| Module / capability | Core capabilities | Release |
| --- | --- | --- |
| Identity and tenancy | Hospital onboarding, facilities, users, roles, SSO, MFA | R1 |
| **Facility setup** | Resumable setup wizard for hospital details, departments, wards, beds, service units, staff positions, reference data, indicator applicability and initial indicator inputs | R1 |
| Patient registry | UHID, demographics, search, merge, ABHA linkage, intake channels, department selection | R1 |
| ABDM | ABHA verification, **Scan and Share**, consent, record exchange | R1 (Scan and Share), R6 (exchange) |
| OPD | Department-driven appointments, queue/tokens, consultation, prescription | R2 |
| IPD | Admission under department, ward/bed allocation, census, transfers, discharge with disposition | R2 |
| EMR | Clinical notes, problem list, documents, discharge summary | R2 |
| Billing and insurance | Charges, invoices, payments, scheme/TPA claims | R2 (basic), R6 (full) |
| **Quality OS** | Complete source catalogue: 356 NQAS + 50 NABH; auto/manual/hybrid calculations, sampling, dashboards, trends, alerts, CAPA, month-end close, provenance | R3 (v1), R7 (v2) |
| LIS | Orders, samples, results, analyzers, critical alerts | R4 |
| RIS | Imaging orders, reports, PACS link | R4 |
| Pharmacy | Formulary, dispensing, stock, stock-out tracking | R4 |
| **Blood Bank** | Donors, collection/testing, component inventory, requisition, cross-match, issue, discards, transfusion reactions | R4 |
| Emergency | Triage, tracking board | R5 |
| ICU | Critical-care charting and live-vitals view | R5 |
| OT | Scheduling, surgical and anaesthesia records | R5 |
| Notifications/realtime | In-app notifications and constrained realtime delivery for notifications/live vitals only | R1/R5 |

**Department model:** departments and wards are tenant configuration rather than separate software modules. OPD and IPD use the configured structure, and indicator applicability is resolved against the same configuration.

## 6. Key User Journeys

### 6.1 Self-registration with ABHA QR

1. Patient arrives at the OPD; the facility displays its QR at the registration area.
2. Patient scans it with an ABDM-enabled app, logs in or creates an ABHA, and shares the profile.
3. The HMIS matches or creates the patient record, issues a token, and shows it on the counter display and in the patient's app. The counter display uses REST polling/refetching; it does not depend on Django Channels.
4. Patient collects the OP slip at the counter; staff confirm any missing details and mark the record **verified**.
5. Doctor sees the patient in the OPD queue.

**Success looks like:** fewer people waiting at the registration counter, accurate demographics, and zero duplicate records created by the flow.

### 6.2 Inpatient stay to quality data

1. Admission records the bed, ward and diagnosis; the daily census captures occupancy.
2. Clinical documentation, orders and charting proceed through the stay.
3. Discharge records a **structured disposition** (routine, LAMA, absconded, referred, death) and a discharge summary.
4. Overnight, the Quality OS updates bed occupancy, length of stay, LAMA and related indicators from this data, with no manual entry.

### 6.3 Monthly quality cycle

1. Quality manager opens the dashboard; indicators for the framework profile (NQAS or NABH) are already calculated.
2. Data-quality warnings (for example missing dispositions) are fixed at source.
3. Out-of-range or worsening indicators raise alerts; the manager opens a **CAPA**, records root cause and actions, and assigns owners.
4. Month-end close locks the values; a committee pack and any required export are generated.
5. A later review checks whether the CAPA's linked indicator improved, then closes or reopens it.

## 7. Feature Requirements (User Stories)

Priority uses MoSCoW (M = must, S = should, C = could). Detailed, testable requirements are in the SRS.

### 7.1 Registration and ABDM

| ID | Story | Pri | Rel |
| --- | --- | --- | --- |
| P-REG-1 | As a clerk, I can search and register patients in under a minute so queues move | M | R1 |
| P-REG-2 | As a clerk, I am warned about likely duplicates before creating a record | M | R1 |
| P-REG-3 | As a patient, I can register by scanning the facility QR and sharing my ABHA profile | M | R1 |
| P-REG-4 | As a clerk, I can see self-registered patients awaiting verification and complete them | M | R1 |
| P-REG-5 | As an admin, I can generate and reprint QR codes per facility, counter or department | M | R1 |
| P-REG-6 | As a patient, I see my token in my app and on the counter screen | M | R1 |
| P-REG-7 | As a clerk, I can create or verify an ABHA at the counter | S | R1 |
| P-REG-8 | As an admin, I can configure token series, slip printing and scheme/category fields per tenant | S | R1 |
| P-REG-9 | As a patient or clerk, I can select the OPD department at registration from the configured departments | M | R1 |
| P-REG-10 | As an admin, I can print department-specific QR codes for ABHA self-registration | S | R1 |

### 7.2 OPD, IPD and EMR

| ID | Story | Pri | Rel |
| --- | --- | --- | --- |
| P-OPD-1 | As a doctor, I see my live queue and a patient's history in one screen | M | R2 |
| P-OPD-2 | As a doctor, I can write structured notes and prescriptions quickly | M | R2 |
| P-IPD-1 | As a nurse, I can admit a patient to a specific bed and see ward occupancy | M | R2 |
| P-IPD-2 | As a ward in-charge, I get a daily census and bed status board | M | R2 |
| P-IPD-3 | As a doctor, I must choose a discharge disposition before discharge | M | R2 |
| P-IPD-4 | As a doctor, I can generate a standard discharge summary | M | R2 |
| P-IPD-5 | As a doctor, I can admit a patient under the consulted/triaged department and allocate a ward/bed within it | M | R2 |
| P-IPD-6 | As a ward in-charge, I can transfer a patient between wards/departments with a recorded reason | M | R2 |
| P-EMR-1 | As a clinician, I see one longitudinal record across OPD, IPD and diagnostics | M | R2 |

### 7.3 Billing and insurance

| ID | Story | Pri | Rel |
| --- | --- | --- | --- |
| P-BIL-1 | As a billing executive, I can bill OPD and IPD services from a configurable tariff | M | R2 |
| P-BIL-2 | As a billing executive, I can take payments and issue receipts | M | R2 |
| P-BIL-3 | As a billing executive, I can handle scheme and TPA pre-authorisation and claims | S | R6 |
| P-BIL-4 | As a government facility admin, I can mark services as free or scheme-covered | M | R2 |

### 7.4 Diagnostics, pharmacy and critical care

| ID | Story | Pri | Rel |
| --- | --- | --- | --- |
| P-LIS-1 | As a doctor, I can order tests and see results with critical flags | M | R4 |
| P-LIS-2 | As a lab tech, analyzer results can flow in automatically | S | R4 |
| P-RIS-1 | As a doctor, I can order imaging and read the report; images open in a viewer | S | R4 |
| P-PHM-1 | As a pharmacist, I can dispense against prescriptions and see stock | M | R4 |
| P-PHM-2 | As a pharmacist, stock-out days are recorded automatically | S | R4 |
| P-EMG-1 | As an ER nurse, I can triage and see a tracking board | M | R5 |
| P-ICU-1 | As an ICU nurse, I can chart vitals and devices on a flowsheet | M | R5 |
| P-OT-1 | As an OT coordinator, I can schedule cases and record surgical and anaesthesia notes | M | R5 |
| P-BBK-1 | As a blood bank technician, I can manage donors, collections, testing and component inventory | M | R4 |
| P-BBK-2 | As a clinician, I can request blood and see requisition/issue status, with timestamps | M | R4 |
| P-BBK-3 | As a blood bank technician, I can record cross-match, issue, discards and transfusion reactions | M | R4 |

### 7.5 Quality OS

| ID | Story | Pri | Rel |
| --- | --- | --- | --- |
| P-QOS-1 | As a quality manager, the Quality OS exposes the complete source-aligned catalogue of 356 NQAS and 50 NABH indicators | M | R3 |
| P-QOS-2 | As a quality manager, I can drill from any indicator value to contributing cases, sampled observations or manual evidence | M | R3 |
| P-QOS-3 | As a quality manager, I see run charts and control charts with signal flags and source-defined frequencies | M | R3 |
| P-QOS-4 | As a quality manager, I get alerts when an enabled indicator breaches a configured target, shows a statistical signal or has required data missing | M | R3 |
| P-QOS-5 | As a quality manager, I can raise, track and close CAPAs linked to indicators | M | R3 |
| P-QOS-6 | As a quality manager, I can lock a period and reproduce the same numbers later using the stored definition version | M | R3 |
| P-QOS-7 | As a quality manager, I am warned about incomplete, inconsistent or insufficient source data | M | R3 |
| P-QOS-8 | As a quality manager, I can filter the catalogue by framework, edition, indicator type/standard, department or specialty, frequency and calculation mode | M | R3 |
| P-QOS-9 | As a government hospital admin, I can enable the NQAS District Hospital profile and its hospital-wide and department/service indicators | M | R3 |
| P-QOS-10 | As a hospital admin, I can enable the NABH 6th Edition profile and applicable organisational/department-specific KPIs | M | R3 |
| P-QOS-11 | As a quality manager, I can enter manual numerator/denominator or count data for indicators whose source methodology requires manual/audit collection | M | R3 |
| P-QOS-12 | As a quality manager, I can manage sampling plans, sampled observations and evidence for audit-based indicators | M | R3 |
| P-QOS-13 | As a platform administrator, I can import and version a new source edition without overwriting historical indicator definitions | M | R3 |
| P-QOS-14 | As a quality manager, I can generate a monthly report and committee pack | S | R3 |
| P-QOS-15 | As a quality manager, I can produce NQAS-oriented and NABH-oriented exports | S | R7 |
| P-QOS-16 | As a quality manager, I can run NQAS/NABH self-assessments with evidence | S | R7 |
| P-QOS-17 | As an admin, I can define custom indicators separate from framework-standard definitions | C | R7 |
| P-QOS-18 | As an admin, I can opt into anonymised benchmarking | C | R7 |
| P-QOS-19 | As a quality manager, every supplied NQAS and NABH indicator has a source reference, applicability and calculation pathway | M | R3 |
| P-QOS-20 | As a quality manager, I can inspect the source sheet/standard and calculation metadata for an indicator | M | R3 |

### 7.6 Notifications and live vitals

| ID | Story | Pri | Rel |
| --- | --- | --- | --- |
| P-RT-1 | As a clinician or administrator, I receive authorised in-app notifications and clinically relevant alerts in near real time, while notification state remains available after reconnect | M | R1 |
| P-RT-2 | As an ICU/ward clinician, I can view authorised patient vitals updating live on a dashboard | M | R5 |
| P-RT-3 | As an ICU/ward clinician, I can continue viewing persisted vitals through REST when live connection is unavailable | M | R5 |
| P-RT-4 | As a hospital user, operational screens such as bed boards, ER boards and OPD token displays remain usable through normal REST refresh/polling and do not depend on the realtime channel | M | R1 |

### 7.7 Administration and platform

| ID | Story | Pri | Rel |
| --- | --- | --- | --- |
| P-ADM-1 | As a tenant admin, I can manage users, roles, departments, wards and beds | M | R1 |
| P-ADM-2 | As a hospital group admin, I can sign in through our identity provider (SSO) | S | R1 |
| P-ADM-3 | As a compliance officer, I can view who accessed a patient record | M | R1 |
| P-ADM-4 | As a clinician, I can use break-glass access with a recorded reason | S | R1 |
| P-ADM-5 | As a platform admin, I can onboard a new hospital in a documented, repeatable way | M | R1 |
| P-SET-1 | As a new hospital admin, I am guided through a resumable setup wizard for facility structure and reference data | M | R1 |
| P-SET-2 | As an admin, I can edit facility configuration later with effective-dated history preserved | M | R1 |
| P-SET-3 | As an admin, I can import beds and staff positions from CSV | S | R1 |

## 8. Government vs Private Configuration

| Area | Government default | Private default |
| --- | --- | --- |
| Registration | Scan and Share + counter, token and OP slip | Scan and Share or counter, optional payment at registration |
| Billing | Free/scheme-covered services, category tracking | Tariff-based billing, TPA and insurance |
| Quality profile | NQAS (District Hospital; 356 supplied indicators) | NABH (6th edition; 50 supplied KPIs) |
| Reporting | Indicators reported up the quality chain | Internal quality committee, assessor evidence |
| Data hosting | India region, optional dedicated database for large facilities | India region, optional dedicated database for groups |

Both profiles can be enabled on one tenant; shared indicators are calculated once.

### 8.1 Quality OS source baseline and product rules

The product baseline is the supplied source set: **356 NQAS District Hospital indicators** (30 hospital-wide KPI-sheet indicators + 326 indicators across 18 department/service sheets) and **50 NABH 6th Edition KPIs** (32 organisational + 18 department-specific), for a total of **406**.

The Quality OS supports three product-level capture pathways: **automatic** from structured HMIS data, **structured/manual form** for source measures requiring human entry or audit, and **hybrid** where system data is combined with sampled observations. A source-specific formula, population, unit or applicability rule always overrides a generic KPI template.

The system must preserve source provenance and historical definition versions so an indicator value can be reproduced against the exact source definition that generated it.

## 9. Release Plan

| Release | Contents | Outcome |
| --- | --- | --- |
| **R1 Foundation** | Tenancy, identity, patient registry, audit, ABDM sandbox integration and **Scan and Share** | A hospital can register patients, including by QR |
| **R2 Core clinical** | OPD, IPD (beds, census, discharge disposition), EMR, billing basics | Day-to-day hospital operations |
| **R3 Quality OS v1** | Import/version the complete 406-indicator source catalogue; automatic calculations from available HMIS data; manual/hybrid audit forms; dashboards, trends, alerts, CAPA and month-end close | Source-aligned NQAS/NABH Quality OS with no catalogue gaps |
| R4 Diagnostics, pharmacy and **blood bank** | LIS, RIS, pharmacy and related source mappings | Activates diagnostic, medication, turnaround-time and stock-out indicators |
| R5 Critical care and surgery | Emergency, ICU, OT and related source mappings | Activates critical-care, infection, surgery, transfusion and specialty indicators |
| R6 Insurance and ecosystem | Claims, TPAs, scheme workflows, full ABDM exchange | Revenue cycle and record exchange |
| R7 Quality OS v2 and hardening | NQAS/NABH self-assessment, approved exports, catalogue governance tooling, benchmarking, performance, pen test, certification prep | Accreditation-oriented hardening and assessment support |

**Minimum viable product:** R1 to R3. This is the smallest release that lets a hospital register patients, run OPD and IPD, and operate the source-aligned Quality OS catalogue with automatic, manual and hybrid indicator pathways plus CAPA.

**Pilot approach (proposed):** 2-3 pilot hospitals (at least one government, one private) from R2, expanding after R3.

## 10. Success Metrics (targets to validate)

| Area | Metric | Initial target |
| --- | --- | --- |
| Registration | Share of OPD registrations via QR in facilities that enable it | Track from pilot; set target after baseline |
| Registration | Median time from arrival to token | Reduce versus pilot baseline |
| Data quality | Share of discharges with a structured disposition | ≥ 98% |
| Data quality | Duplicate patient rate | Below pilot baseline and falling |
| Quality OS | Time for a quality manager to produce monthly indicators | From days to under an hour |
| Quality OS | Source catalogue coverage | 100% of the supplied **406** NQAS/NABH indicators loaded, versioned and provenance-linked before R3 exit |
| Quality OS | Share of enabled indicators with an explicit calculation mode and source mapping | 100% |
| Quality OS | CAPAs closed with effectiveness evidence | Rising quarter on quarter |
| Reliability | Monthly availability | 99.9% |
| Realtime | Notification/live-vitals delivery and reconnect behaviour | Validate in pilot; no loss of persisted state |
| Security | Cross-tenant data exposure incidents | 0 |
| Adoption | Weekly active users per licensed user | Track and target after pilot |
| Commercial | Onboarding time per hospital | Days, not weeks (refine after pilot) |

## 11. Commercial Packaging (hypothesis)

- Subscription by facility size (bed bands), with module bundles: Core (registration, OPD, IPD, EMR, billing), Diagnostics (LIS, RIS, pharmacy), Critical Care (emergency, ICU, OT), and **Quality OS** as an add-on or included at higher tiers.
- Government deployments may use different procurement models (state contracts, per-facility licences). To be validated with prospective customers.
- Premium option: dedicated database/instance for large or high-assurance customers.

## 12. Assumptions and Dependencies

**Assumptions**

- Hospitals have reliable enough internet at registration and ward points; brief outages are tolerated through limited offline behaviour.
- Facilities can be registered in the ABDM facility registry and onboarded as health information providers.
- Hospitals will accept structured data capture (for example a mandatory discharge disposition) in exchange for automation.

**Dependencies**

- ABDM sandbox access, product certification milestones and production onboarding.
- Supplied NQAS workbook and NABH 6th Edition KPI section as the current source-of-truth snapshots for the Quality OS catalogue.
- Payer and scheme integration specifications.
- Indian-region cloud hosting.

## 13. Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| ABDM API changes (older and newer versions coexist) | Registration channel breaks | Adapter layer supporting both; sandbox regression tests |
| Indicator definitions diverge from official standards | Loss of trust at assessment | Source-controlled catalogue, versioning, provenance, golden tests and quality review |
| NABH source text licensing is unclear | Product/export restrictions or rework | Confirm reproduction rights before customer-facing redistribution; preserve source references |
| Manual/sampled indicators are omitted because HMIS data is incomplete | False sense of coverage | Auto/manual/hybrid modes, sampling workflows and data-quality completeness dashboard |
| Poor source data capture | Unreliable indicators | Mandatory structured fields, data-quality dashboard |
| Cross-tenant leakage | Severe trust and legal impact | Row-level security, automated isolation tests, penetration testing |
| Low adoption by busy staff | Incomplete data | Fast UX, training, pilot feedback loops |
| Scope breadth (12 modules) | Delays | Phased releases; MVP limited to R1-R3 |
| Regulatory interpretation (DPDP, ABDM) | Rework | Legal review before finalising |
| Realtime channel overload or overuse | Clinical/display degradation or unnecessary coupling | Keep Django Channels strictly limited to notifications/live vitals; use REST polling for other operational screens; scale ASGI/Channels separately |

## 14. Open Questions

1. Confirm the controlled source/version/hash process for future NQAS workbook revisions.
2. Confirm licensing and permission to embed NABH indicator text, definitions and methodology in customer-facing screens and exports.
3. Government reporting formats and any state-specific portals to export to.
4. Which TPAs and schemes to integrate first.
5. Languages required for patient-facing screens and slips.
6. Pilot hospital selection and success criteria.
7. Functional-bed denominator method for occupancy and turnover (day-weighted vs period average).
8. Initial ASGI/Channels scaling thresholds and concurrency assumptions for notifications and live vitals.

## 15. Glossary

| Term | Meaning |
| --- | --- |
| ABDM | Ayushman Bharat Digital Mission |
| ABHA | Ayushman Bharat Health Account (14-digit health ID) |
| BOR / ALOS / BTR | Bed occupancy rate / average length of stay / bed turnover rate |
| CAPA | Corrective and preventive action |
| HIP | Health information provider (in ABDM) |
| LAMA | Leaving against medical advice |
| NABH | National Accreditation Board for Hospitals and Healthcare Providers |
| NQAS | National Quality Assurance Standards (NHSRC) |
| OP slip | Outpatient slip issued at registration |
| UHID | Unique hospital identification number |
| Django | Python web framework used for the HMIS backend modular monolith |
| DRF | Django REST Framework; REST API layer for the HMIS backend |
| Celery | Distributed background task processing framework used for asynchronous jobs |
| Django Channels | ASGI/WebSocket layer restricted to notifications and live vitals dashboards |