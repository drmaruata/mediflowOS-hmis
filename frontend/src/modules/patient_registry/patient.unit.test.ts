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
  birthYearFromDemographics,
  buildRegistrationPayload,
  isValidIndianMobile,
  sameTenant,
  verificationLabel,
} from "./patient.api";

describe("buildRegistrationPayload", () => {
  it("sends the date of birth when one is entered", () => {
    const payload = buildRegistrationPayload({
      name: "Asha Lakshmi",
      gender: "female",
      dob: "1984-03-12",
      age_years: "",
      mobile: "9876543210",
      abha_number: "",
      intake_department_id: "22222222-2222-4222-8222-222222222222",
    });
    expect(payload.demographics).toEqual({
      name: "Asha Lakshmi",
      gender: "female",
      dob: "1984-03-12",
    });
    expect(payload.contact).toEqual({ mobile: "9876543210" });
    expect(payload.intake_channel).toBe("counter");
  });

  it("falls back to approximate age only when no date of birth is given", () => {
    const payload = buildRegistrationPayload({
      name: "Ravi Kumar",
      gender: "male",
      dob: "",
      age_years: "42",
      mobile: "",
      abha_number: "",
      intake_department_id: "dept",
    });
    expect(payload.demographics).toEqual({
      name: "Ravi Kumar",
      gender: "male",
      age_years: 42,
    });
    expect(payload.contact).toBeUndefined();
    expect(payload.abha_number).toBeUndefined();
  });

  it("never carries a UHID — the server mints it (REG-001)", () => {
    const payload = buildRegistrationPayload({
      name: "Asha Lakshmi",
      gender: "female",
      dob: "1984-03-12",
      age_years: "",
      mobile: "9876543210",
      abha_number: "12-3456-7890-1234",
      intake_department_id: "dept",
    });
    expect("uhid" in payload).toBe(false);
    expect("uhid" in payload.demographics).toBe(false);
    expect(payload.abha_number).toBe("12-3456-7890-1234");
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
