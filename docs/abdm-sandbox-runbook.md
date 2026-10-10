# ABDM sandbox runbook (ABD-017)

How to run, record and triage the ABDM profile-share test case that SRS
requirement **ABD-017** asks for: *"the system shall pass the ABDM profile-share
test case in sandbox for each supported API version."*

## Status: ABD-017 is NOT verified

> **ABD-017 is not green until a recorded real-sandbox run — or the recorded
> gated replay run with credentials — is pasted into the [Run log](#run-log)
> section below. Skips do not count.**

Nothing in this repository may be read as proof that the sandbox exchange
works. Concretely, as of the last entry in the Run log:

- `tests/integration/test_abdm_sandbox.py` is **gated on `ABDM_SANDBOX_RUN`**.
  Without that variable every case is skipped, and a skipped case has proved
  nothing at all about the sandbox.
- The gated run that *has* been recorded is a **hermetic replay**: it posts a
  signed profile-share callback to our own `/api/v1/abdm-callbacks/` endpoint
  through the Django test database. It never opens a connection to ABDM. It
  proves our side of the exchange — the HMAC, the payload validation, the
  tenant resolution, the consent record, the token — and nothing about the
  sandbox's.
- The live half, **the sandbox calling our endpoint**, has never been run in
  any recorded entry, because this environment has no ABDM credentials and no
  network path to the sandbox. See [The live run](#the-live-run-separate-manual-step).

`docs/traceability.md` therefore reports ABD-017 as `deferred` in the
per-requirement matrix and under Known gaps, which is the honest state. Closing
that gap means appending a Run log entry below, not editing the status here.

## What the replay covers

`tests/integration/test_abdm_sandbox.py` seeds one tenant, one facility
carrying the HIP ID the gateway names and one OPD-enabled department — the
entire setup the real flow needs — then signs and posts the profile-share
callback exactly as the gateway does. It asserts three things:

1. **The acknowledgement**: `status == "ok"`, the gateway's `request_id` echoed
   back, a token id, a patient id, and the consent provenance
   (`timestamp`/`source_app`/`purpose`/`facility_id`). No link token — the one
   credential an acknowledgement must never echo (ABD-012).
2. **The consent row**: exactly one `abdm.consent_event` for the tenant,
   carrying the payload's own `sourceApp`, the purpose and the facility, with a
   `raw_profile_hash` that ties it to the exact payload shared (ABD-011).
3. **The token**: one `opd.token` issued against the patient the
   acknowledgement names (ABD-010).

The cases are parametrised per **API version**: `v1.0` and `v3`. Those are the
two the repository's documented contract covers — architecture doc §8.2 records
v1.0 and v3 paths coexisting and requires the `abdm-gateway` module to sit
behind an adapter that supports both. The callback contract itself is
version-agnostic, so the version is carried in the gateway request id, which
also makes each parametrised case a fresh scan rather than a replay (idempotency
would answer the second identical request id with the first acknowledgement,
ABD-006).

**Coverage caveat.** The sandbox's *authoritative* list of profile-share API
versions could not be resolved offline, and is deliberately not invented here.
Two versions are what the repo documents; confirm the full list against ABDM's
sandbox documentation and extend `API_VERSIONS` before claiming ABD-017 as
"each supported API version".

## Prerequisites

Run from `backend/` with the test profile (`DJANGO_SETTINGS_MODULE` is
`config.settings.test`, an in-memory SQLite database — no PostgreSQL, Redis or
ABDM sandbox credentials are needed for the replay itself).

| Variable | Required | What it does |
| --- | --- | --- |
| `ABDM_SANDBX_RUN` | yes | The gate. Set to any non-empty value (`1`) to let the module's cases run at all. Without it they are skipped, and a skip is not a verification. |
| `ABDM_CLIENT_SECRET` | for a recorded run | The shared secret the gateway signs Scan and Share callbacks with. `config/settings/test.py` reads it at import and only falls back to a fixed literal when the environment carries none, so exporting the real credential makes both settings and the test sign with it. Without it the replay still runs, signed with the deterministic test literal — record that explicitly if you do it. |
| `ABDM_SANDBOX_BASE_URL` | for a sandbox-shaped setup | The outbound sandbox root. The hermetic replay does not make outbound calls and does not need it; export it so the settings-level gate validates it and so the live step below can reach the sandbox. It must be https on a hostname containing `sbx` (Task 14's sandbox-only gate, `require_sandbox_base_url`); anything else raises `ImproperlyConfigured` at settings import, which is deliberate. |

**Secret precedence.** `ABDM_CLIENT_SECRET` from the environment wins; the
fallback is `settings.ABDM_CLIENT_SECRET`, which the test profile has already
populated from that same variable with a deterministic literal when the
environment carried none. The precedence is written out in
`_sandbox_secret()` in the test so it is visible in one place rather than
inherited from an import side effect.

Never write a real credential into any file, including this runbook. Use a
placeholder (`<sandbox-client-secret>`) in anything committed, and export the
real value in the shell that runs the command.

## Running the replay

PowerShell, from `backend/`:

```powershell
$env:ABDM_SANDBX_RUN = "1"
$env:ABDM_CLIENT_SECRET = "<sandbox-client-secret>"
$env:ABDM_SANDBOX_BASE_URL = "https://sbx.example.invalid"

C:\Python314\python -m pytest -c pyproject.toml ../tests/integration/test_abdm_sandbox.py -q
```

bash, from `backend/`:

```bash
ABDM_SANDBX_RUN=1 \
ABDM_CLIENT_SECRET='<sandbox-client-secret>' \
ABDM_SANDBOX_BASE_URL=https://sbx.example.invalid \
  python -m pytest -c pyproject.toml ../tests/integration/test_abdm_sandbox.py -q
```

> **Why `-c pyproject.toml ../tests/...` and not the shorter
> `python -m pytest tests/integration/test_abdm_sandbox.py -q`.** The pytest
> configuration (`DJANGO_SETTINGS_MODULE`, `testpaths`, `--strict-markers`)
> lives in `backend/pyproject.toml`, and `backend/` is the working directory.
> Given a bare `tests/...` argument, pytest climbs from `tests/integration/`
> towards the filesystem root looking for a config file, finds none (the
> nearest one is in a parent of the working directory), and runs with no
> Django settings configured — every test file then fails to collect with
> `ImproperlyConfigured: Requested setting REST_FRAMEWORK`. This is a property
> of the repository layout, not of this test: `python -m pytest
> ../tests/integration/test_abdm_callback.py -q` fails the same way.
> `-c pyproject.toml` pins the rootdir, and `../tests/...` is the path from
> `backend/`.

Expected output for two API versions:

```
..                                                                    [100%]
2 passed in 2.5s
```

## Expected acknowledgement

A successful profile share answers `200` with:

```json
{
  "status": "ok",
  "token": "81fc9b7d-f162-424f-b0bb-fb8eceb8a074",
  "request_id": "sbx-profile-share-v1.0",
  "patient_id": "0059cc66-35a1-4a9e-bafc-49f48446fd11",
  "consent_event": {
    "timestamp": "2026-10-10T06:39:15.583134-05:00",
    "source_app": "abdm-sandbox-replay-v1.0",
    "purpose": "registration",
    "facility_id": "c3ddbc6a-b7c7-4c97-a1f9-18fd9ee0a086"
  }
}
```

(the example is a captured body from the gated replay; ids are examples, and
`timestamp` is ISO-8601 in the server's local timezone. `request_id` is the
gateway's own request id and `source_app` is the payload's `sourceApp`.)

Two acknowledgements are notable answers rather than successes:

- `{"status": "duplicate", ...}` with `200` — the same gateway request id was
  already processed (ABD-006). Expected on a genuine retry; not expected from a
  correctly parametrised run, where each version carries its own request id.
- `{"status": "ambiguous", "token": null, ...}` — the profile matched more than
  one registered patient, so nothing was linked and a verification-queue entry
  was created for the front desk (ABD-009). The replay's profile is unique to
  the tenant it seeds, so it must not occur; if it does, the seeded tenant was
  not clean.

## Failure triage

| Symptom | Cause | What to check |
| --- | --- | --- |
| `401` `{"status": "rejected", "detail": "Authentication failed"}` | Signature/secret mismatch (ABD-005). | The digest is HMAC-SHA256 over the **raw** request body — the exact bytes on the wire — with the hex digest in `X-ABDM-Signature`. A body re-serialized after signing (different key order, different separators, a client that re-encodes a dict) breaks it. Confirm the secret precedence: `ABDM_CLIENT_SECRET` in the environment wins, and the test reads `os.environ` first then `settings`. An empty secret fails closed outside `DEBUG`, so it is refused rather than accepted. |
| `400` `Missing required callback field: requestId` (or `timestamp`, `profile`) | Payload schema (ABD-007). | All three keys are mandatory and none is defaulted. A payload without them is malformed, not repairable. |
| `400` `Invalid or stale timestamp` | Stale or unparseable timestamp (ABD-007). | The window is `ABDM_MAX_SKEW_SECONDS`, 300 seconds by default. Fix a drifting clock rather than widening the window; a wider window silently weakens the replay check. |
| `404` `Unknown facility HIP ID` | The facility's HIP ID is not registered (ABD-004). | The callback resolves the tenant from `Facility.abdm_hip_id`, and the payload's `facilityId` must name a facility that exists in this installation. Register the facility's HIP ID first (tenant onboarding stamps `abdm.abdm_hip_id`). |
| `404` `Supplied department is not part of this facility` | A `departmentId` from another tenant (ABD-013). | The gateway is not trusted to name our departments. Leave `departmentId` out of the replayed payload, or seed the department inside the tenant the HIP ID resolves to. |
| `409` `No OPD department is configured` | No OPD-enabled department (ABD-010). | The token has to go somewhere. Seed a department with `opd_enabled=True` for the tenant. |
| `503` `ABDM_SANDBOX_MISCONFIGURED` / `ABDM_SANDBOX_UNCONFIGURED` | The outbound sandbox gate (Task 14). | Not this replay — it makes no outbound call. These come from the ABHA create/verify actions at the counter, which fail closed when no sandbox base URL is configured or when it is not an https `sbx` URL. Set `ABDM_SANDBOX_BASE_URL` correctly and retry. |
| Connection failure / `ABDM_SANDBOX_UNREACHABLE` / `ABDM_REQUEST_FAILED` | Network or URL. | Same as above: a counter-side symptom, not a replay one. Check the URL, then the network path. A non-2xx sandbox response is mirrored as `ABDM_REQUEST_FAILED`. |
| `ImproperlyConfigured` at collection time | `ABDM_SANDBOX_BASE_URL` is not sandbox-shaped, or `PATIENT_FIELDS_KEY` is unset outside `DEBUG`. | Task 14's gate runs at settings import. Use an https URL on an `sbx` hostname; the test profile always supplies the encryption passphrase. |
| `ImproperlyConfigured: Requested setting REST_FRAMEWORK` | pytest config not picked up. | See the note in [Running the replay](#running-the-replay): use `-c pyproject.toml`. |

## Run log

Every run that anyone claims as evidence goes here, verbatim, with the date,
the operator, whether it reached the live sandbox, and the exact command.
**An entry that did not reach the live sandbox is evidence about our code only
and does not count towards ABD-017.**

### 2026-10-10 — controller's recorded baseline (skip)

- **Operator:** controller (Task 19 review), this environment.
- **Reached the live sandbox:** no. No ABDM credentials, no network path.
- **Command:** `C:\Python314\python -m pytest -c pyproject.toml ../tests/integration/test_abdm_sandbox.py -q` from `backend/`, no `ABDM_SANDBX_RUN`.
- **Result:** `2 skipped in 0.10s`.
- **What it proves:** the gate works. **Not a verification.**

### 2026-10-10 — hermetic gated replay (throwaway secret)

- **Operator:** Task 19 implementer, this environment.
- **Reached the live sandbox:** no. Hermetic: Django test database, our own
  endpoint, no network.
- **Command:** `ABDM_SANDBX_RUN=1 ABDM_CLIENT_SECRET=<throwaway-not-a-real-secret> ABDM_SANDBOX_BASE_URL=https://sbx.local.invalid python -m pytest -c pyproject.toml ../tests/integration/test_abdm_sandbox.py -q` from `backend/`.
- **Result:** `2 passed in 2.46s` (one pass per API version, `v1.0` and `v3`).
- **What it proves:** the callback contract the gateway exercises — ack shape,
  one consent row, one OPD token — holds end to end against our own endpoint.
  **Not a live-sandbox verification.** The secret was a throwaway string and the
  base URL pointed at a non-existent host; no outbound call was made or needed.

_(No live-sandbox run has been recorded. Add the next entry above this line.)_

## The live run (separate, manual step)

The replay cannot satisfy ABD-017 on its own, because the requirement is about
the **sandbox**. The live run is the exchange in the other direction:

1. A facility's HIP ID is registered in the ABDM sandbox for this tenant, and
   the sandbox is configured with our callback URL
   (`/api/v1/abdm-callbacks/`) and with the credential exported as
   `ABDM_CLIENT_SECRET`.
2. Someone scans the facility's QR with an ABDM-enabled app and shares a
   profile. The sandbox posts the callback to us.
3. The callback is authenticated, the tenant resolved from the HIP ID, the
   patient matched or provisionally registered, the OPD token issued, the
   consent event recorded, and the acknowledgement returned to the app.
4. The operator repeats it per supported API version, and pastes each run —
   command, output, the acknowledgement body, and the version exercised — into
   the [Run log](#run-log) with the date and their name.

That step needs **network egress to the ABDM sandbox and real sandbox
credentials**, which this environment does not have. Until such an entry exists
in the Run log, `docs/traceability.md` keeps ABD-017 as `deferred` and no
report may claim the requirement is met.
