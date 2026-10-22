/**
 * Unit tests for the patient registry's pure helpers (REG-001, REG-007,
 * REG-008).
 *
 * The UHID pin is the load-bearing one (REG-001): the identifier is
 * server-minted, so the create payload builder must never carry a `uhid`
 * key — a client that typed, generated or pre-filled a UHID would break the
 * per-tenant sequence the registry owns.
 */

import { describe, expect, it } from "vitest";

import {
  ageFromDob,
  birthYearFromDemographics,
  buildRegistrationPayload,
  isValidIndianMobile,
  localDateISO,
  sameTenant,
  verificationLabel,
} from "./patient.api";

describe("buildRegistrationPayload", () => {
  it("sends the name, gender, dob, address and mobile the clerk entered", () => {
    const payload = buildRegistrationPayload({
      name: "Asha Lakshmi",
      gender: "female",
      dob: "1984-03-12",
      address: " 12 MG Road, Mysuru ",
      mobile: "9876543210",
      abha_number: "",
      intake_department_id: "22222222-2222-4222-8222-222222222222",
    });
    expect(payload.demographics).toEqual({
      name: "Asha Lakshmi",
      gender: "female",
      dob: "1984-03-12",
    });
    expect(payload.address).toEqual({ full: "12 MG Road, Mysuru" });
    expect(payload.contact).toEqual({ mobile: "9876543210" });
    expect(payload.intake_channel).toBe("counter");
  });

  it("omits the contact and ABHA keys when none was entered", () => {
    const payload = buildRegistrationPayload({
      name: "Ravi Kumar",
      gender: "male",
      dob: "1980-01-02",
      address: "4 Church Street, Chennai",
      mobile: "",
      abha_number: "",
      intake_department_id: "dept",
    });
    expect(payload.contact).toBeUndefined();
    expect(payload.abha_number).toBeUndefined();
  });

  it("never carries a UHID — the server mints it (REG-001)", () => {
    const payload = buildRegistrationPayload({
      name: "Asha Lakshmi",
      gender: "female",
      dob: "1984-03-12",
      address: "12 MG Road, Mysuru",
      mobile: "9876543210",
      abha_number: "12-3456-7890-1234",
      intake_department_id: "dept",
    });
    expect("uhid" in payload).toBe(false);
    expect("uhid" in payload.demographics).toBe(false);
    expect(payload.abha_number).toBe("12-3456-7890-1234");
  });
});

describe("ageFromDob", () => {
  const iso = (date: Date): string =>
    `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  // A birth date exactly N years back (plus an optional day nudge) so the
  // expectations hold on any day the suite runs.
  const yearsAgo = (years: number, dayOffset = 0): Date => {
    const date = new Date();
    date.setFullYear(date.getFullYear() - years);
    date.setDate(date.getDate() + dayOffset);
    return date;
  };

  it("computes whole years with the birthday-today rule", () => {
    expect(ageFromDob(iso(yearsAgo(40)))).toBe(40);
    expect(ageFromDob(iso(yearsAgo(40, 1)))).toBe(39);
    expect(ageFromDob(iso(yearsAgo(1)))).toBe(1);
  });

  it("returns null for an empty, unparseable or future date", () => {
    expect(ageFromDob("")).toBeNull();
    expect(ageFromDob("not-a-date")).toBeNull();
    expect(ageFromDob(iso(yearsAgo(-1)))).toBeNull();
  });
});

describe("birthYearFromDemographics", () => {
  it("reads the year from a stored date of birth, ISO or bare-year", () => {
    expect(birthYearFromDemographics({ dob: "1984-03-12" })).toBe(1984);
    expect(birthYearFromDemographics({ dob: "1980" })).toBe(1980);
  });

  it("reads the registry's yearOfBirth key and converts an approximate age", () => {
    expect(birthYearFromDemographics({ yearOfBirth: 1975 })).toBe(1975);
    expect(birthYearFromDemographics({ age_years: 42 })).toBe(
      new Date().getFullYear() - 42,
    );
  });

  it("returns null when the record carries no usable birth key", () => {
    expect(birthYearFromDemographics({})).toBeNull();
  });
});

describe("isValidIndianMobile", () => {
  it("accepts the canonical, prefixed and trunk-zero forms the server canonicalises", () => {
    expect(isValidIndianMobile("9876543210")).toBe(true);
    expect(isValidIndianMobile("+91 98765 43210")).toBe(true);
    expect(isValidIndianMobile("09876543210")).toBe(true);
  });

  it("refuses a fragment, a non-Indian leading digit and an empty value", () => {
    expect(isValidIndianMobile("98765")).toBe(false);
    expect(isValidIndianMobile("1234567890")).toBe(false);
    expect(isValidIndianMobile("")).toBe(false);
  });
});

describe("sameTenant", () => {
  it("renders nothing without a resolved tenant session", () => {
    expect(sameTenant({ tenant_id: "t-1" }, null)).toBe(false);
  });

  it("accepts the session's own rows and refuses a foreign tenant's", () => {
    expect(sameTenant({ tenant_id: "t-1" }, "t-1")).toBe(true);
    expect(sameTenant({ tenant_id: "t-2" }, "t-1")).toBe(false);
  });
});

describe("verificationLabel", () => {
  it("gives every state its own visible text — never colour alone", () => {
    expect(verificationLabel("pending")).toBe("Pending verification");
    expect(verificationLabel("verified")).toBe("Verified");
    expect(verificationLabel("ambiguous")).toBe("Ambiguous");
    expect(new Set(["pending", "verified", "ambiguous"]).size).toBe(3);
  });
});

describe("localDateISO", () => {
  it("formats the local calendar day, zero-padded — not the UTC day of toISOString", () => {
    expect(localDateISO(new Date(2026, 0, 2))).toBe("2026-01-02");
    expect(localDateISO(new Date(2026, 6, 14))).toBe("2026-07-14");
    expect(localDateISO(new Date(2026, 11, 25))).toBe("2026-12-25");
  });
});
