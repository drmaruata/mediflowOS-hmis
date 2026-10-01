# SaaS HMIS: Software Requirements Specification (SRS)

**Version:** 0.5 (draft) | **Status:** For review | **Date:** 1 Oct 2026 **Derived from:** PRD v0.5 and Architecture Document v0.6 **Changes from v0.3:** incorporates the complete 356-indicator NQAS District Hospital workbook and 50-KPI NABH Hospital Accreditation Standards 6th Edition baseline; adds source provenance, applicability, sampling, manual/hybrid calculation and versioning requirements for Quality OS. **Structure:** modelled on ISO/IEC/IEEE 29148 headings

> Performance and capacity figures are **proposed targets** to be validated with pilots. Items marked TBD need a decision (see section 10).

---

## 1. Introduction

### 1.1 Purpose

This SRS defines the testable functional and non-functional requirements of the multi-tenant SaaS Hospital Management Information System (HMIS), including the ABHA QR self-registration channel and the Quality OS module for NQAS and NABH.

### 1.2 Scope

The system serves government and private hospitals (average \~100 beds, hundreds of tenants). It covers registration, OPD, IPD, emergency, ICU, OT, LIS, RIS, pharmacy, **blood bank**, billing/insurance, EMR and Quality OS. Native mobile apps, telemedicine video and payer-side systems are out of scope for v1. NQAS support is limited to District Hospital level in v1.

### 1.3 Conventions

- "Shall" marks a mandatory requirement. Priority: **M** must, **S** should, **C** could.
- "Rel" is the release from the PRD (R1 to R7).
- Requirement IDs are stable: `<AREA>-<NNN>`.

### 1.4 Definitions

See the PRD glossary. Additional terms: **Tenant** (a hospital or group using the platform), **Facility** (a physical hospital within a tenant), **Intake point** (a counter or department where patients start a visit), **Disposition** (discharge outcome).

### 1.5 References

- Architecture Document v0.4; PRD v0.3.
- ABDM sandbox documentation and developer forum (Scan and Share, profile share).
- NHSRC NQAS material (Area of Concern H); IPHS-based outcome indicator methodology.
- NABH Accreditation Standards for Hospitals, 6th edition (effective 1 Jan 2025).
- NQAS District Hospital Outcome Indicator workbook supplied for this project (`NQAS_Outcome_Indicator_final.xlsx`).
- `SaaS HMIS Quality OS Indicator Specification v0.2.md`.
- Digital Personal Data Protection Act and applicable rules; HL7 FHIR; HL7 v2; DICOM.

## 2. Overall Description

### 2.1 Product perspective

A web-based, multi-tenant SaaS. Browser clients (Vite React SPA) talk to a **Django + Django REST Framework modular monolith** running under ASGI, backed by PostgreSQL with row-level security, Redis, object storage and **Celery + Celery Beat** background workers. **Django Channels is a constrained realtime adapter used only for the real-time notification engine and live vitals dashboards.** External systems: ABDM gateway, lab analyzers, imaging modalities/PACS, payers, payment gateways, SMS/WhatsApp/email providers.

### 2.2 Major functions

Registration and identity; ABDM integration; outpatient and inpatient care; emergency, critical care and surgery; diagnostics; pharmacy; billing and insurance; electronic medical record; quality indicators, trends and CAPA; audit; administration.

### 2.3 User classes

Registration clerk, doctor, nurse, lab technician, radiologist/technician, pharmacist, billing/TPA executive, ward in-charge, medical superintendent/CEO, quality manager, tenant administrator, platform administrator, self-registering patient (via ABDM app), integration systems.

### 2.4 Operating environment

Modern desktop browsers (evergreen Chrome, Edge, Firefox, Safari) on hospital workstations and tablets; wall-mounted displays for token boards; production hosting in an Indian cloud region.

### 2.5 Constraints

- All protected health information is stored and processed in India.
- Tenant isolation is enforced in the database (row-level security).
- Standards: FHIR (clinical interchange), HL7 v2 (lab), DICOM (imaging).
- Indicator definitions must follow official NQAS and NABH sources.

### 2.6 Assumptions and dependencies

See PRD section 12. Key dependencies: ABDM facility registration and certification, official NQAS/NABH indicator documents, hospital network quality, and availability of analyzer/PACS interfaces.

## 3. External Interface Requirements

### 3.1 User interfaces

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| UI-001 | The system shall provide a responsive web UI usable at 1366x768 and above, and on tablets for ward use | M | R1 |
| UI-002 | The system shall support keyboard-driven data entry for registration, orders and billing | M | R1 |
| UI-003 | The system shall provide a kiosk-style counter display for tokens with auto-reconnect and no interactive login | M | R1 |
| UI-004 | The system shall meet WCAG 2.1 AA for core workflows | S | R2 |
| UI-005 | The system shall support English initially and be localisation-ready for Hindi and regional languages | S | R2 |
| UI-006 | The system shall print OP slips, receipts, discharge summaries, reports and QR codes in configurable templates | M | R1 |
| UI-007 | The system shall show a clear "unsynced" indicator for any offline-queued entry and shall not present clinical orders as saved until confirmed by the server | M | R2 |

### 3.2 Software and communication interfaces

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| INT-001 | The system shall expose a versioned REST API with an OpenAPI specification | M | R1 |
| INT-002 | The system shall integrate with the ABDM gateway for ABHA services and profile sharing, supporting both older and newer API versions via an adapter | M | R1 |
| INT-003 | The system shall expose and consume HL7 FHIR resources at integration boundaries | M | R2 |
| INT-004 | The system shall exchange HL7 v2 messages with laboratory analyzers through a facility-side bridge | S | R4 |
| INT-005 | The system shall integrate with a DICOM server for imaging metadata and viewing | S | R4 |
| INT-006 | The system shall provide adapters for payment gateways with idempotent webhook handling | S | R6 |
| INT-007 | The system shall provide adapters for TPA/insurer and scheme (including PM-JAY) workflows behind a common interface | S | R6 |
| INT-008 | The system shall send notifications through SMS, WhatsApp and email providers via a provider-agnostic interface | S | R2 |
| INT-009 | The system shall support OIDC/SAML single sign-on for tenant identity providers | S | R1 |
| INT-010 | The system shall support file-based export of regulatory and accreditation reports | S | R7 |
| INT-011 | The application backend shall expose versioned REST endpoints implemented with Django REST Framework and publish an OpenAPI specification | M | R1 |
| INT-012 | The system shall use Django Channels WebSocket consumers **only** for the real-time notification engine and live vitals dashboards | M | R1 |
| INT-013 | The system shall use REST polling/refetching for OPD token displays, bed boards, emergency boards and other non-vitals operational screens | M | R1 |
| INT-014 | Background jobs and scheduled processing shall run through Celery/Celery Beat and shall not depend on Django Channels for delivery or execution | M | R1 |

### 3.3 Hardware interfaces

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| HW-001 | The system shall support standard receipt/slip printers and A4 printers | M | R1 |
| HW-002 | The system shall support barcode/QR scanners as keyboard-wedge input | S | R2 |
| HW-003 | The system shall support sample-label and wristband printing | S | R4 |

## 4. Functional Requirements

### 4.1 Identity, tenancy and administration (TEN)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| TEN-001 | The system shall support multiple tenants, each with one or more facilities, on shared infrastructure | M | R1 |
| TEN-002 | The system shall isolate tenant data at the database level so that no query under one tenant's context returns another tenant's rows | M | R1 |
| TEN-003 | The system shall support a dedicated-database option per tenant using the same application | S | R7 |
| TEN-004 | The system shall provide role-based access control with configurable roles and permissions per tenant | M | R1 |
| TEN-005 | The system shall support attribute-based rules (department, assigned patient, facility) in addition to roles | S | R2 |
| TEN-006 | The system shall support multi-factor authentication for privileged roles | M | R1 |
| TEN-007 | The system shall support break-glass access that requires a reason and raises an alert and audit record | S | R1 |
| TEN-008 | The system shall let tenant administrators manage facilities, departments, wards, rooms, beds (with a functional/non-functional flag), users and tariffs | M | R1 |
| TEN-009 | The system shall let tenant administrators select an accreditation profile (NQAS District Hospital, NABH, both, or custom) | M | R3 |
| TEN-010 | The platform administrator shall be able to onboard a tenant through a repeatable, documented process with seed configuration | M | R1 |
| TEN-011 | The system shall store each facility's ABDM identifiers and registration status | M | R1 |

### 4.2 Facility setup and configuration (SET)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| SET-001 | The system shall provide a resumable setup wizard capturing hospital identity, ownership, facility level/type, address, ABDM/HFR identifiers and accreditation profile | M | R1 |
| SET-002 | The system shall let authorised users define departments with OPD-enabled/IPD-enabled flags | M | R1 |
| SET-003 | The system shall let authorised users define wards under departments and beds under wards, including functional/non-functional status | M | R1 |
| SET-004 | The system shall support service units without beds (OT, labour room, laboratory, radiology, pharmacy, blood bank, mortuary, CSSD and similar) with type tags | M | R1 |
| SET-005 | The system shall record sanctioned and in-position staff positions by designation, specialty and department | M | R1 |
| SET-006 | The system shall store reference data used as indicator denominators, including catchment population, ambulances and configured essential commodity lists | M | R1 |
| SET-007 | The setup wizard shall show applicable indicators and collect their required baseline/manual inputs | M | R1 |
| SET-008 | The setup wizard shall be resumable and shall flag incomplete steps | M | R1 |
| SET-009 | Authorised users shall be able to edit configuration after setup | M | R1 |
| SET-010 | Configuration changes shall be effective-dated and versioned so locked indicator periods retain the historical settings | M | R1 |
| SET-011 | Historical departments, wards, beds and service units shall be deactivated rather than deleted | M | R1 |
| SET-012 | All configuration changes shall be audited | M | R1 |
| SET-013 | The system shall support CSV import/export of beds and staff positions | S | R1 |

### 4.3 Patient registration and registry (REG)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| REG-001 | The system shall register a patient and generate a unique hospital identification number (UHID) at the end of registration | M | R1 |
| REG-002 | The system shall allow search by UHID, name, mobile, ABHA number/address, and approximate age/year of birth | M | R1 |
| REG-003 | The system shall warn of probable duplicates before saving a new patient | M | R1 |
| REG-004 | The system shall support merging duplicate records with full history and an audit trail, and shall allow an authorised un-merge | M | R2 |
| REG-005 | The system shall record the intake channel (counter, ABHA QR, appointment) for every registration | M | R1 |
| REG-006 | The system shall mark records as **provisional** or **verified**, and shall list provisional records in a verification queue | M | R1 |
| REG-007 | The system shall store patient demographics, contact, address, scheme/category and consent flags with field-level validation | M | R1 |
| REG-008 | The system shall protect highly sensitive identifiers with application-level encryption | M | R1 |
| REG-009 | The system shall let staff create a new ABHA or verify an existing one at the counter, using ABDM-supported methods | S | R1 |
| REG-010 | The system shall issue an OPD token, series configurable per facility/department, at registration | M | R1 |
| REG-011 | The system shall print an OP slip with token, UHID and visit details | M | R1 |
| REG-012 | The system shall let the clerk or patient select the OPD department from configured departments | M | R1 |
| REG-013 | The system shall support department-specific QR codes so ABHA self-registration can resolve to the intended department when the ABDM flow permits | S | R1 |

### 4.4 ABHA QR self-registration and ABDM (ABD)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| ABD-001 | The system shall generate a printable QR code per facility and optionally per counter/department that encodes the facility's ABDM identifier and an intake-point code | M | R1 |
| ABD-002 | The system shall let administrators regenerate or revoke a QR code | M | R1 |
| ABD-003 | The system shall accept ABDM profile-share callbacks on an authenticated, rate-limited endpoint | M | R1 |
| ABD-004 | The system shall resolve the tenant and facility from the callback's facility identifier and shall set tenant context before any data access | M | R1 |
| ABD-005 | The system shall verify the authenticity of every gateway call per the ABDM specification and reject unauthenticated calls | M | R1 |
| ABD-006 | The system shall process each gateway request identifier at most once (idempotency) and return the original outcome on retry | M | R1 |
| ABD-007 | The system shall validate timestamps and payload fields and respond with a well-formed acknowledgement including the issued token | M | R1 |
| ABD-008 | The system shall match a shared profile first by ABHA number within the tenant, then by demographic candidate search | M | R1 |
| ABD-009 | If exactly one strong match exists the system shall link to it; if multiple candidates exist it shall create a verification-queue entry; if none exist it shall create a provisional patient | M | R1 |
| ABD-010 | The system shall issue a token for the intake point and shall make it available to the counter display and the patient's app via the acknowledgement | M | R1 |
| ABD-011 | The system shall record the profile share as a consent event with timestamp, source, purpose and facility | M | R1 |
| ABD-012 | The system shall store ABDM link tokens encrypted and use them only for care-context linking | M | R1 |
| ABD-013 | The system shall remain fully usable through the counter channel if the ABDM gateway is unavailable | M | R1 |
| ABD-014 | The system shall alert administrators on abnormal callback failure or volume | S | R1 |
| ABD-015 | The system shall model intake points by type (OPD, pharmacy, lab, billing) so Scan and Share can extend beyond OPD | S | R4 |
| ABD-016 | The system shall support linking care contexts and sharing health records with consent via ABDM | S | R6 |
| ABD-017 | The system shall pass the ABDM profile-share test case in sandbox for each supported API version | M | R1 |

### 4.5 Outpatient department (OPD)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| OPD-001 | The system shall maintain per-doctor/department queues ordered by token and priority rules | M | R2 |
| OPD-002 | The system shall record visit type (new/follow-up), referral-in source and referral-out flag | M | R2 |
| OPD-003 | The system shall capture registration time, consultation start and end for wait-time reporting | M | R2 |
| OPD-004 | The system shall support appointments with slots, rescheduling and reminders | S | R2 |
| OPD-005 | The system shall record structured consultation notes, diagnoses (coded) and prescriptions | M | R2 |
| OPD-006 | The system shall allow ordering of lab and imaging tests from the consultation | M | R4 |
| OPD-007 | The system shall display the patient's prior encounters during consultation | M | R2 |
| OPD-008 | The system shall record follow-up advice and next-visit date | M | R2 |

### 4.6 Inpatient department (IPD)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| IPD-001 | The system shall admit a patient to a specific bed and record admission time, source, diagnosis and responsible clinician | M | R2 |
| IPD-002 | The system shall maintain a bed master with ward, class, functional status and current occupancy | M | R2 |
| IPD-003 | The system shall provide a live bed board and prevent double allocation of a bed | M | R2 |
| IPD-004 | The system shall record transfers between beds and wards with timestamps | M | R2 |
| IPD-005 | The system shall capture a **midnight census** snapshot each day per ward and facility | M | R2 |
| IPD-006 | The system shall require a discharge **disposition** from a controlled list (routine, LAMA, absconded, referred, death, other as configured) before completing discharge | M | R2 |
| IPD-007 | The system shall require a discharge summary with standard content, including cause of death where applicable, for all dispositions including LAMA | M | R2 |
| IPD-008 | The system shall record nursing initial assessment and re-assessments | M | R2 |
| IPD-009 | The system shall support handover notes between shifts | S | R2 |
| IPD-010 | The system shall record referral-out destination and reason | M | R2 |
| IPD-011 | The system shall capture discharge time to support discharge-time monitoring | S | R2 |
| IPD-012 | The system shall admit a patient under a department and allocate a ward and bed within that department | M | R2 |
| IPD-013 | The system shall record admission source and transfers between wards/departments with timestamp and reason | M | R2 |

### 4.7 Emergency, ICU and OT (EMG, ICU, OT)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| EMG-001 | The system shall record triage category, arrival time and time to first assessment | M | R5 |
| EMG-002 | The system shall show a real-time emergency tracking board | M | R5 |
| EMG-003 | The system shall support medico-legal case flagging | S | R5 |
| ICU-001 | The system shall provide vitals and fluid-balance flowsheets with configurable frequency | M | R5 |
| ICU-002 | The system shall record invasive devices (insertion and removal times) to compute device-days | M | R5 |
| ICU-003 | The system shall support early-warning scoring configuration and alerts | S | R5 |
| ICU-004 | The system shall provide a live vitals dashboard for authorised ICU/ward users, with persisted vitals remaining the source of truth | M | R5 |
| OT-001 | The system shall schedule operations by theatre, team and time with conflict detection | M | R5 |
| OT-002 | The system shall record pre-operative checklist, anaesthesia record and operative notes | M | R5 |
| OT-003 | The system shall record prophylactic antibiotic administration times relative to incision | S | R5 |
| OT-004 | The system shall record unplanned returns to theatre | S | R5 |

### 4.8 Laboratory (LIS) and Imaging (RIS)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| LIS-001 | The system shall manage test orders, sample collection with identification, receipt and result entry | M | R4 |
| LIS-002 | The system shall receive results from analyzers via HL7 v2 and require validation before release | S | R4 |
| LIS-003 | The system shall flag and track communication of critical results with acknowledgement time | M | R4 |
| LIS-004 | The system shall record order, collection, receipt and report timestamps for turnaround reporting | M | R4 |
| LIS-005 | The system shall support amendment of released reports with versioning and notification | M | R4 |
| LIS-006 | The system shall support internal quality control records for laboratory tests | C | R4 |
| RIS-001 | The system shall manage imaging orders, scheduling, study status and reports | S | R4 |
| RIS-002 | The system shall link studies to a DICOM server and open images in a viewer | S | R4 |
| RIS-003 | The system shall record imaging order, performed and report timestamps | S | R4 |
| RIS-004 | The system shall track critical imaging result communication | S | R4 |

### 4.9 Pharmacy (PHM)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| PHM-001 | The system shall maintain a formulary and stock by batch and expiry | M | R4 |
| PHM-002 | The system shall dispense against prescriptions and record substitutions | M | R4 |
| PHM-003 | The system shall record daily stock-out status per essential item to compute stock-out days | S | R4 |
| PHM-004 | The system shall support reporting of medication errors and adverse drug reactions | M | R4 |
| PHM-005 | The system shall flag look-alike/sound-alike and high-alert medications | S | R4 |
| PHM-006 | The system shall record medication administration for inpatients | M | R4 |

### 4.10 Blood Bank (BBK)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| BBK-001 | The system shall manage donor registration, donation/collection records and mandatory testing status | M | R4 |
| BBK-002 | The system shall maintain blood component inventory by unit, component, group, status, collection and expiry dates | M | R4 |
| BBK-003 | The system shall support blood requisition, patient linkage and request timestamps | M | R4 |
| BBK-004 | The system shall support cross-match and compatibility recording | M | R4 |
| BBK-005 | The system shall record issue, including replacement/voluntary source where required, and requisition-to-issue time | M | R4 |
| BBK-006 | The system shall record discards and reasons | M | R4 |
| BBK-007 | The system shall record transfusion reactions and link them to issued units/patients | M | R4 |
| BBK-008 | The system shall provide structured data needed by applicable NQAS and NABH transfusion/blood-bank indicators | M | R4 |

### 4.11 Billing and insurance (BIL)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| BIL-001 | The system shall maintain configurable tariffs by service, ward class and payer category | M | R2 |
| BIL-002 | The system shall create OPD and IPD bills, accept payments and issue receipts | M | R2 |
| BIL-003 | The system shall support services marked as free or scheme-covered, with category tracking | M | R2 |
| BIL-004 | The system shall support advances, refunds, discounts and approvals with audit | S | R2 |
| BIL-005 | The system shall support scheme/TPA pre-authorisation and claim submission tracking | S | R6 |
| BIL-006 | The system shall reconcile payments and produce daily collection reports | S | R2 |

### 4.12 Electronic medical record (EMR)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| EMR-001 | The system shall present a longitudinal patient record across OPD, IPD, diagnostics and procedures | M | R2 |
| EMR-002 | The system shall keep clinical entries append-only, with amendments stored as new versions | M | R2 |
| EMR-003 | The system shall support clinical documents and attachments | M | R2 |
| EMR-004 | The system shall maintain problem list, allergies and active medications | M | R2 |
| EMR-005 | The system shall map core clinical data to FHIR resources for exchange | M | R2 |
| EMR-006 | The system shall record falls, pressure injuries and similar safety events as structured entries | M | R2 |

### 4.13 Quality OS (QOS)

The Quality OS catalogue for this SRS is based on the supplied source documents. It contains **406 source definitions: 356 NQAS District Hospital indicators and 50 NABH 6th Edition KPIs**. The source-aligned companion specification is **`SaaS HMIS Quality OS Indicator Specification v0.2.md`** and the machine-readable seed is **`SaaS HMIS Quality OS Indicator Catalog v0.2.json`**.

**Source precedence rule:** the definition stored in the active indicator version is normative. Generic calculation helpers must never override a source-specific numerator, denominator, population, unit, frequency, lag, applicability or direct-count/median operator.

**Catalogue and provenance**

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| QOS-001 | The system shall load and version the complete supplied catalogue of 356 NQAS District Hospital indicators and 50 NABH 6th Edition KPIs | M | R3 |
| QOS-002 | Each indicator definition shall retain framework, edition, source document, source sheet/standard, source serial number, scope, name, type/dimension, unit, direction where applicable, frequency, numerator, denominator, formula/operator, source-of-data, applicability and definition version | M | R3 |
| QOS-003 | Each indicator shall declare a calculation pathway: automatic, structured/manual, or hybrid | M | R3 |
| QOS-004 | The system shall store sampling requirement/method, sample-size guidance, reporting lag and system-capture guidance when supplied by the source | M | R3 |
| QOS-005 | The system shall support NQAS District Hospital-wide and department/service scopes and NABH organisational and named specialty scopes | M | R3 |
| QOS-006 | The system shall enable/disable applicable indicators by tenant without modifying framework-standard definitions | M | R3 |
| QOS-007 | A source-definition change shall create a new definition version and shall not overwrite historical values | M | R3 |
| QOS-008 | The system shall preserve source provenance including source file/document, version/hash, page/sheet or locator and import timestamp | M | R3 |
| QOS-009 | The system shall expose the complete supplied NQAS workbook catalogue, including source-specific Discharge Rate indicators | M | R3 |
| QOS-010 | The system shall expose the complete supplied NABH 6th Edition KPI catalogue, including organisational and specialty scope | M | R3 |
| QOS-011 | The system shall preserve source-specific formulas and direct-count/median operators without forcing a numerator/denominator model | M | R3 |
| QOS-012 | The system shall support controlled source-import versioning so revised source files create new definitions without overwriting history | M | R3 |
| QOS-013 | The system shall support custom indicators under a separate CUSTOM framework namespace | C | R7 |

**Automatic, structured/manual and hybrid calculation**

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| QOS-020 | The system shall derive quality facts from source-module events and maintain append-only fact inputs | M | R3 |
| QOS-021 | The system shall compute source-defined numerator, denominator, value and calculation status for every enabled indicator for its configured period | M | R3 |
| QOS-022 | The engine shall support count, percentage, rate, ratio, time, median and other source-defined operators without forcing a percentage representation | M | R3 |
| QOS-023 | The engine shall support Monthly, Yearly, Continuous and cumulative/YTD monitoring frequencies where specified | M | R3 |
| QOS-024 | The system shall support manual numerator/denominator or count entry where source methodology or system limitations require it | M | R3 |
| QOS-025 | The system shall provide controlled sampling/audit workflows for indicators requiring sample selection, observation or audit evidence | M | R3 |
| QOS-026 | The system shall honour reporting lag and distinguish provisional from locked values | M | R3 |
| QOS-027 | The system shall calculate enabled NQAS and NABH indicators when the required structured source inputs exist | M | R3-R5 |
| QOS-028 | Shared computations shall only be reused when numerator, denominator, population, unit, frequency, applicability and definition semantics match across frameworks | M | R3 |

**NQAS source baseline**

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| QOS-030 | The system shall load the 30 hospital-wide NQAS KPI-sheet indicators | M | R3 |
| QOS-031 | The system shall load the 326 NQAS department/service indicators from the 18 supplied sheets | M | R3 |
| QOS-032 | The system shall preserve the NQAS source categories Productivity, Efficiency, Clinical care and safety, and Service Quality Indicator | M | R3 |
| QOS-033 | The system shall retain source-specific NQAS indicators such as department-level Discharge Rate without collapsing them into a generic KPI | M | R3 |
| QOS-034 | The system shall map every NQAS source sheet to the configured facility/service structure and capture pathway | M | R3 |
| QOS-035 | The import validator shall verify NQAS totals and category counts before source publication | M | R3 |

**NABH source baseline**

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| QOS-040 | The system shall load all 32 NABH organisational KPIs from the 6th Edition KPI section | M | R3 |
| QOS-041 | The system shall load all 18 NABH department-specific KPIs and their specialty applicability | M | R3 |
| QOS-042 | The system shall preserve NABH standard references such as PSQ 3a, PSQ 3b and PSQ 3d | M | R3 |
| QOS-043 | The system shall record NABH source guidance for sampling, inpatient applicability, reporting lag and HIS/EMR capture where provided | M | R3 |
| QOS-044 | The system shall provide manual numerator/denominator entry when required by source methodology or when system data cannot safely collate the required value | M | R3 |
| QOS-045 | The system shall enforce specialty applicability for department-specific NABH KPIs based on tenant-configured scope | M | R3 |

**Data quality, verification, trends and reporting**

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| QOS-050 | The system shall run data-quality checks such as missing source fields, invalid denominators, census gaps, late data, insufficient sample and calculation exceptions | M | R3 |
| QOS-051 | The system shall allow drill-through from an indicator value to contributing clinical cases, source observations or manual evidence subject to role permissions and audit | M | R3 |
| QOS-052 | The system shall record source numerator, denominator, unit, value, definition version and calculation timestamp with every value | M | R3 |
| QOS-053 | The system shall support period close with immutable snapshots and versioned corrections | M | R3 |
| QOS-054 | The system shall reproduce any locked indicator period using the stored definition version and source inputs | M | R3 |
| QOS-060 | The system shall chart enabled indicators as run charts and support appropriate control-chart types and signal rules | M | R3 |
| QOS-061 | The system shall support month-on-month, year-on-year, moving-average and cumulative/YTD views where relevant | M | R3 |
| QOS-062 | The system shall raise alerts on configured target breach, statistical signal, sustained worsening, missing required data or overdue indicator collection | M | R3 |
| QOS-063 | The system shall allow users to configure alert recipients and internal thresholds without altering framework-standard formulas | S | R3 |
| QOS-070 | The system shall allow CAPAs to be raised from indicator alerts, incidents, audits, complaints or manually | M | R3 |
| QOS-071 | CAPA shall record issue, severity, owner, due date, RCA, corrective/preventive action, evidence and effectiveness indicator | M | R3 |
| QOS-072 | The system shall support CAPA states raised, RCA, action plan, implementation, verification and closed, with reopen on ineffective verification | M | R3 |
| QOS-073 | The system shall generate framework-oriented indicator registers/reports and preserve indicator provenance | S | R3-R7 |
| QOS-074 | The system shall support NQAS District Hospital and NABH KPI exports in approved formats | S | R7 |

### 4.14 Audit and platform services (AUD, PLT)

| ID | Requirement | Pri | Rel |
| --- | --- | --- | --- |
| AUD-001 | The system shall log every create, read, update and delete of patient data with user, time, source, action and reason (for break-glass) | M | R1 |
| AUD-002 | The audit log shall be append-only and tamper-evident | M | R1 |
| AUD-003 | The system shall let authorised users view the access history of a patient record | M | R1 |
| AUD-004 | The system shall retain audit records per a configurable retention policy | M | R1 |
| PLT-001 | The system shall provide the **real-time notification engine** for authorised in-app notifications and clinically relevant alerts, with notification state persisted before realtime delivery | M | R1 |
| PLT-002 | The system shall provide a **live vitals dashboard** for authorised ICU/ward users using Django Channels when connected, with REST fallback when the WebSocket is unavailable | M | R5 |
| PLT-003 | The system shall provide REST polling/refetching for non-vitals operational displays including bed status, OPD queues/token displays and emergency boards | M | R1 |
| PLT-004 | The system shall run background jobs reliably with retry, back-off and visibility using Celery/Celery Beat | M | R1 |
| PLT-005 | The system shall provide file storage for documents and evidence with access control | M | R1 |
| PLT-006 | The system shall support feature flags per tenant | S | R1 |
| PLT-007 | The system shall provide in-app and external notifications with user preferences | S | R2 |
| PLT-008 | Django Channels shall not be used for OPD token displays, bed boards, emergency boards, ordinary CRUD updates, ABDM callbacks, background jobs or domain-to-domain communication | M | R1 |

## 5. Non-Functional Requirements

### 5.1 Performance and capacity (proposed targets)

| ID | Requirement | Pri |
| --- | --- | --- |
| NFR-PERF-001 | API p95 latency shall be under 300 ms for common read operations at expected peak load | M |
| NFR-PERF-002 | Patient search shall return results within 1 second for tenants with up to 1 million patient records | M |
| NFR-PERF-003 | The system shall support at least 150 concurrent users per tenant and 15,000 platform-wide at launch scale, scalable toward 45,000 | M |
| NFR-PERF-004 | An ABDM profile-share callback shall be acknowledged within the time the gateway expects, targeting under 2 seconds | M |
| NFR-PERF-005 | Nightly indicator computation shall complete for all tenants within a defined overnight window (TBD) | M |
| NFR-PERF-006 | Dashboard indicator views shall load within 3 seconds from snapshot data | S |

### 5.2 Availability and recovery

| ID | Requirement | Pri |
| --- | --- | --- |
| NFR-AVL-001 | Monthly availability shall be at least 99.9% excluding agreed maintenance | M |
| NFR-AVL-002 | Recovery point objective shall be 5 minutes or less | M |
| NFR-AVL-003 | Recovery time objective shall be 1 hour or less | M |
| NFR-AVL-004 | Backups shall use continuous log archiving with daily snapshots and a cross-region encrypted copy within India | M |
| NFR-AVL-005 | Restore shall be tested at least quarterly | M |
| NFR-AVL-006 | Deployments shall use progressive rollout and backward-compatible database migrations | M |

### 5.3 Security

| ID | Requirement | Pri |
| --- | --- | --- |
| NFR-SEC-001 | All traffic shall use TLS 1.2 or higher | M |
| NFR-SEC-002 | Data at rest shall be encrypted with managed keys; highly sensitive fields shall additionally use application-level encryption with keys outside the database | M |
| NFR-SEC-003 | The application database role shall not bypass row-level security | M |
| NFR-SEC-004 | Automated tests shall attempt cross-tenant access on every tenant-owned table; any success shall fail the build | M |
| NFR-SEC-005 | Secrets shall be held in a secrets manager and never in code or images | M |
| NFR-SEC-006 | The system shall protect against common web vulnerabilities (injection, XSS, CSRF, broken access control) and undergo independent penetration testing before general availability and annually | M |
| NFR-SEC-007 | Session and token lifetimes, lockout and password rules shall be configurable per tenant within platform minimums | S |
| NFR-SEC-008 | Public endpoints (including ABDM callbacks) shall be rate limited and monitored | M |
| NFR-SEC-009 | Dependencies and container images shall be scanned for vulnerabilities in CI | M |

### 5.4 Privacy and compliance

| ID | Requirement | Pri |
| --- | --- | --- |
| NFR-PRV-001 | All PHI shall be stored and processed in Indian regions | M |
| NFR-PRV-002 | The system shall record consent events and support purpose limitation | M |
| NFR-PRV-003 | The system shall support data-principal rights workflows (access, correction, erasure where legally permitted) | S |
| NFR-PRV-004 | The system shall support a documented breach-notification process | M |
| NFR-PRV-005 | Retention periods shall be configurable per record type and respect legal minimums | M |
| NFR-PRV-006 | Cross-tenant benchmarking shall use only aggregated, anonymised data and require explicit tenant opt-in | M |

### 5.5 Usability and accessibility

| ID | Requirement | Pri |
| --- | --- | --- |
| NFR-USE-001 | Registration of a returning patient shall be completable in under 30 seconds of keyboard-driven interaction in usability tests | S |
| NFR-USE-002 | Core workflows shall conform to WCAG 2.1 AA | S |
| NFR-USE-003 | The UI shall show clear error and recovery messages for unsynced or failed saves | M |

### 5.6 Reliability and data integrity

| ID | Requirement | Pri |
| --- | --- | --- |
| NFR-REL-001 | Clinical records shall be append-only with versioned amendments | M |
| NFR-REL-002 | State changes that trigger downstream processing shall use a transactional outbox so events are not lost or duplicated | M |
| NFR-REL-003 | Indicator values shall be reproducible from locked snapshots and the recorded definition version | M |
| NFR-REL-004 | Integration failures shall be queued, retried and surfaced to administrators | M |
| NFR-REL-005 | Realtime delivery through Django Channels shall be treated as a secondary delivery mechanism; loss or delay of a WebSocket connection shall not lose clinical data or persisted notification state | M |

### 5.7 Maintainability and operability

| ID | Requirement | Pri |
| --- | --- | --- |
| NFR-MNT-001 | Modules shall interact only through defined interfaces and events; direct cross-module table access is prohibited | M |
| NFR-MNT-002 | The system shall emit traces, metrics and structured logs for Django/DRF API, ASGI/Channels consumers, Celery workers and integrations | M |
| NFR-MNT-003 | CI shall include unit tests, tenant-isolation tests, indicator golden tests and static analysis | M |
| NFR-MNT-004 | Indicator definitions shall be data-driven so framework editions can be updated without redeploying application code | M |

### 5.8 Interoperability and localisation

| ID | Requirement | Pri |
| --- | --- | --- |
| NFR-INT-001 | Clinical exchange shall conform to FHIR and ABDM profiles where applicable | M |
| NFR-INT-002 | The system shall be localisation-ready (text externalised, date/number formats, right content in slips and notices) | S |

## 6. Data Requirements

### 6.1 Key entities

Tenant, Facility, Department, Ward, Bed, User, Role, Patient (UHID, ABHA linkage, verification status), Visit/Encounter, Token, Admission, Census snapshot, Discharge (with disposition), Order, Result, Prescription, Dispense, Charge, Invoice, Payment, Claim, Clinical document, Incident, Consent event, Blood unit/component, Cross-match, Transfusion reaction, Audit event, Indicator definition, Indicator value (snapshot), Benchmark, CAPA, Assessment, Evidence.

### 6.2 Required structured fields (quality by design)

| Source | Fields |
| --- | --- |
| IPD | Admission and discharge timestamps; disposition; functional-bed register; midnight census; ward/department; referral destination |
| OPD | Visit type; referral-out flag; registration and consultation times |
| Emergency/ICU/OT | Triage and assessment times; device insertion/removal; prophylaxis and incision times; unplanned returns |
| LIS/RIS | Order, collection/performed, report times; critical result communication |
| Pharmacy | Stock-out status by day for essential items; error and ADR reports |
| Blood Bank | Donor/collection data; unit/component identifiers; inventory/expiry; requisition, cross-match and issue timestamps; replacement/voluntary source; discards; transfusion reactions |
| EMR | Discharge summary completion; falls and pressure injuries; infection surveillance entries |
| Incidents | Type, severity, department, harm level |

### 6.3 Retention and archival

Configurable per record type. Locked indicator snapshots and CAPA records shall be retained at least as long as accreditation cycles require (TBD with customers).

## 7. Quality Indicator Source Baseline and Calculation Specification

### 7.1 Source inventory

| Framework | Source | Scope | Count | Catalogue artifact |
| --- | --- | --- | ---: | --- |
| NQAS | `NQAS_Outcome_Indicator_final.xlsx` | District Hospital | 356 | `SaaS HMIS Quality OS Indicator Specification v0.2.md` |
| NABH | `NABH Hospital Accreditation Standard 6th Edition January 2025.pdf` | 6th Edition; organisational + specialty | 50 | `SaaS HMIS Quality OS Indicator Specification v0.2.md` |
| Total | Both | Quality OS | **406** | — |

The NQAS workbook contains 30 hospital-wide KPI rows and 326 indicators across 18 department/service sheets. The NABH source contains 32 organisational KPIs and 18 department-specific KPIs in its dedicated KPI section.

### 7.2 NQAS indicator taxonomy

All 356 NQAS indicators are retained with their source type/category: Productivity, Efficiency, Clinical care and safety, or Service Quality Indicator. The Quality OS must preserve the source sheet and serial number because department/service definitions can have the same indicator name with different populations or calculation contexts.

### 7.3 NABH indicator taxonomy

All 50 NABH indicators are retained with source standard references and scope. The 32 organisational KPIs are distinct from the 18 department-specific KPIs. Department-specific scope is explicit and may be enabled only when that specialty/service is in the tenant's scope.

The supplied NABH standard states that indicators should use HIS/EMR data where possible, but a manual numerator/denominator provision is required where the system cannot collate them. It also specifies sampling and guidance for audit-based KPIs. These are therefore modelled as calculation mode and sampling metadata, not as optional implementation notes.

### 7.4 Core calculation contracts

The following are implementation patterns only. The source-specific definition stored in the catalogue is authoritative.

| Indicator | Baseline treatment | Unit |
| --- | --- | --- |
| Bed occupancy rate | Patient bed-days × 100 ÷ source-defined bed-days denominator | % |
| Average length of stay | Patient bed-days ÷ source-defined included discharges | days |
| Bed turnover rate | Source-defined included discharges ÷ source-defined bed denominator | source-defined |
| LAMA rate | NQAS KPI-sheet: LAMA cases × 100 ÷ admissions; other source contexts use their own stored formula | source-defined |
| Absconding rate | NQAS A&E: absconding cases × 100 ÷ A&E cases attended | % |
| Referral-out rate | Source-defined referred cases × 100 ÷ source-defined admissions | source-defined |

Generic formulas must never overwrite a source-specific formula, population, unit or denominator.

### 7.5 NQAS source-specific rules

- Patient bed-days in the Quality OS remain based on the **midnight census** where that is the NQAS source method.
- The NQAS KPI-sheet LAMA Rate is stored and calculated as a **percentage**; the NQAS A&E Absconding Rate is A&E-specific and is a **percentage**.
- NQAS source-specific Discharge Rate indicators remain separate catalogue entries with their original operator/unit semantics.
- Source-specific indicators with frequency `Yearly`, `Monthly` or other source values retain that frequency.
- Where the workbook provides no numerator/denominator and instead defines a direct count or median (for example some sterilization and external quality score indicators), the engine shall use the source calculation text rather than invent a denominator.
- Department-specific `Discharge Rate` indicators in the supplied workbook are valid catalogue entries and are not removed merely because the generic architecture starter list did not include a discharge-rate KPI.

### 7.6 NABH source-specific rules

- Organisation-wide KPI identifiers and PSQ standard references are preserved exactly as the source baseline.
- Department-specific KPIs preserve specialty applicability.
- Infection KPIs such as CAUTI, VAP and CLABSI use device-day denominators and source definitions.
- SSI is treated as a surveillance indicator with provisional/late-update behaviour when the surveillance period extends beyond the month.
- Sampled audit indicators store sample plan and evidence separately from automatically derived facts.
- Cumulative/YTD reporting is supported for indicators whose source methodology specifies it, such as the needlestick injury rate.

### 7.7 Golden test examples

Golden tests shall be source-specific. In particular, the NQAS KPI-sheet LAMA rate and NQAS A&E Absconding Rate shall use their source denominators/units; generic legacy tests that encoded per-1,000 rates for these two indicators are obsolete and shall not be used as acceptance criteria. Additional golden tests shall be added for representative NQAS and NABH indicators from each calculation mode: percentage, rate per 1,000/device-day, ratio, time, count and manual sampled audit.

### 7.8 Full source catalogue

The complete 406-row source-aligned catalogue is maintained in `SaaS HMIS Quality OS Indicator Specification v0.2.md`; `SaaS HMIS Quality OS Indicator Catalog v0.2.json` is the machine-readable seed generated from the same source baseline. The specification is normative; the JSON is the import representation.

## 8. Constraints, Assumptions, Dependencies

- ABDM API behaviour, versions and certification timelines are controlled by ABDM; the system shall isolate this behind an adapter.
- NQAS support is limited to District Hospital level in v1; NABH indicator content depends on the edition in force.
- Hospital network, printers, display screens and analyzer interfaces are customer-provided.
- Legal interpretation of DPDP, ABDM and retention rules requires counsel's confirmation.

## 9. Verification and Acceptance

| Area | Verification method |
| --- | --- |
| Tenant isolation | Automated cross-tenant tests on every table; penetration test |
| Scan and Share | ABDM sandbox test cases for each API version; replay and idempotency tests; load test at peak OPD rates |
| Realtime notification engine | WebSocket authentication/authorization tests, persistence-before-delivery tests, reconnect/fallback tests, tenant/facility isolation tests |
| Live vitals dashboard | WebSocket authorization tests, incremental update tests, REST fallback tests, persistence/source-of-truth tests |
| Realtime scope isolation | Verify Channels is not used by token boards, bed boards, emergency boards, ABDM callbacks or background jobs |
| Indicators | Golden tests per indicator; reconciliation of sample months against manual registers in pilot hospitals |
| CAPA workflow | Scenario tests covering raise, RCA, action, verification, reopen and closure |
| Performance | Load tests at 150 concurrent users per tenant and platform-scale simulation |
| Availability and DR | Restore drills; failover tests |
| Usability | Task-based testing with registration clerks, nurses and quality managers |
| Compliance | Documented control mapping reviewed by counsel; third-party audit readiness |

## 10. Open Issues

| # | Issue |
| --- | --- |
| 1 | Functional-bed denominator method for NQAS occupancy/turnover where a source definition is ambiguous; preserve the source definition and obtain formal product-owner confirmation before release lock |
| 2 | Controlled process for importing revised NQAS workbooks, including version/hash/provenance |
| 3 | NABH 6th Edition licensing/permission for reproducing indicator text, definitions and guidance in customer-facing UI and exports |
| 4 | Exact government reporting templates and state portals |
| 5 | Overnight compute window and per-tenant data volumes |
| 6 | Retention periods for audit, clinical and quality records |
| 7 | Offline scope of ward workflows |
| 8 | TPA and scheme integrations for R6 |
| 9 | Languages for patient-facing outputs |
## 11. Traceability (summary)

| PRD goal | SRS areas | Architecture section | Release |
| --- | --- | --- | --- |
| G1 Faster registration | SET, REG, ABD, OPD, UI-003 | 6, 8 | R1 |
| G2 Single patient record | REG, EMR, IPD, OPD | 6, 10 | R1-R2 |
| G3 Automated indicators | QOS-001 to QOS-013, QOS-020 to QOS-028, QOS-030 to QOS-035, QOS-040 to QOS-045, QOS-050 to QOS-063 | 9 | R3-R5 |
| G4 Closed-loop CAPA | QOS-070 to QOS-072 | 9.8 | R3 |
| G5 NQAS and NABH | TEN-009, QOS-001 to QOS-013, QOS-030 to QOS-035, QOS-040 to QOS-045, QOS-050 to QOS-074 | 9 | R3-R7 |
| G6 Security and compliance | TEN, AUD, NFR-SEC, NFR-PRV | 7, 11 | R1 |
| G7 Scale | NFR-PERF, NFR-AVL, TEN-001, INT-011 to INT-014 | 2, 4, 13, 15 | R1-R7 |