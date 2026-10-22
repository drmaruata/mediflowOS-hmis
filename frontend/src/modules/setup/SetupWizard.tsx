/**
 * SetupWizard — the resumable ten-step facility setup screen (SET-001,
 * SET-007, SET-008, SET-009; UI_UX §7 /admin/setup, persona tenant admin).
 *
 * GET /api/v1/setup/ is the spine: it always carries all ten steps with
 * their status and complete flag, so the whole wizard is derived from it —
 * the percentage (n×10%), the stepper's flags, and the first incomplete
 * step the wizard opens on when a session resumes (SET-008). The client
 * never optimistically marks a step done; the save mutation invalidates
 * ["setup"] and the refetched spine is what flips the UI.
 *
 * Keyboard contract (UI-002): step headings are landmarks (h1/h2), every
 * stepper entry is a reachable button, Enter submits the active step form,
 * and Ctrl+S saves a draft (the StepFooter wiring). The dirty flag is
 * lifted from the active step so the stepper and beforeunload guard
 * navigation away from unsaved edits.
 *
 * shortcut: the doc's CSV import interaction is deferred — only beds and
 * staff-positions have import endpoints and this task builds no import UI;
 * revisit with the Quality OS/bulk-config work.
 */

import { useEffect, useRef, useState } from "react";
import type { ComponentType } from "react";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import type { StepComponentProps } from "./components/StepFooter";
import { fetchSetupSteps } from "./setup.api";
import type { SetupStep, SetupStepKey } from "./setup.api";
import AbdmHfrIdsStep from "./steps/AbdmHfrIdsStep";
import AccreditationStep from "./steps/AccreditationStep";
import AddressStep from "./steps/AddressStep";
import DepartmentsWardsBedsStep from "./steps/DepartmentsWardsBedsStep";
import HospitalIdentityStep from "./steps/HospitalIdentityStep";
import IndicatorsBaselineStep from "./steps/IndicatorsBaselineStep";
import OwnershipLevelStep from "./steps/OwnershipLevelStep";
import ReferenceDataStep from "./steps/ReferenceDataStep";
import ServiceUnitsStep from "./steps/ServiceUnitsStep";
import StaffPositionsStep from "./steps/StaffPositionsStep";

interface StepMeta {
  label: string;
  title: string;
  Component: ComponentType<StepComponentProps>;
}

/** SETUP_STEP_KEYS owns the order; this map only names and binds screens. */
const STEP_META: Record<SetupStepKey, StepMeta> = {
  hospital_identity: {
    label: "Hospital",
    title: "Hospital identity",
    Component: HospitalIdentityStep,
  },
  ownership_level: {
    label: "Ownership",
    title: "Ownership level",
    Component: OwnershipLevelStep,
  },
  address: {
    label: "Address",
    title: "Facility address",
    Component: AddressStep,
  },
  abdm_hfr_ids: {
    label: "ABDM & HFR IDs",
    title: "ABDM & HFR identifiers",
    Component: AbdmHfrIdsStep,
  },
  accreditation: {
    label: "Accreditation",
    title: "Accreditation profile",
    Component: AccreditationStep,
  },
  departments_wards_beds: {
    label: "Departments/Wards/Beds",
    title: "Departments, wards & beds",
    Component: DepartmentsWardsBedsStep,
  },
  service_units: {
    label: "Service Units",
    title: "Service units",
    Component: ServiceUnitsStep,
  },
  staff_positions: {
    label: "Staff Positions",
    title: "Staff positions",
    Component: StaffPositionsStep,
  },
  reference_data: {
    label: "Reference Data",
    title: "Reference data",
    Component: ReferenceDataStep,
  },
  indicators_baseline: {
    label: "Baseline Inputs",
    title: "Indicator baseline inputs",
    Component: IndicatorsBaselineStep,
  },
};

const CONFIRM_MESSAGE = "Discard unsaved changes to this step?";

export default function SetupWizard() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [dirty, setDirty] = useState(false);
  const restoredRef = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const previousIndexRef = useRef(activeIndex);

  const setupQuery = useQuery({
    queryKey: ["setup"],
    queryFn: fetchSetupSteps,
  });
  const steps: SetupStep[] | null =
    setupQuery.isSuccess && Array.isArray(setupQuery.data) ? setupQuery.data : null;

  // Resumption (SET-008): open on the first incomplete step exactly once,
  // when the spine first arrives — later refetches must never yank the user
  // back while they work. Idempotent under StrictMode's double effect.
  useEffect(() => {
    if (steps === null || restoredRef.current) return;
    restoredRef.current = true;
    const firstIncomplete = steps.findIndex((step) => !step.complete);
    if (firstIncomplete >= 0) {
      setActiveIndex(firstIncomplete);
    }
  }, [steps]);

  // On a step change the previously focused control unmounts, which would
  // drop focus to <body>; land it on the new step's heading instead
  // (UI-002's "focus moves to the next field" clause). The previous-index
  // guard skips the mount run so loading the screen never steals focus and
  // stays idempotent under StrictMode's double effect.
  useEffect(() => {
    if (previousIndexRef.current === activeIndex) return;
    previousIndexRef.current = activeIndex;
    headingRef.current?.focus();
  }, [activeIndex]);

  // The tab-level half of the dirty guard; the in-wizard half confirms on
  // Back and stepper jumps.
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  if (setupQuery.isPending) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading setup state…
      </p>
    );
  }

  if (steps === null) {
    return (
      <div className="flex flex-col gap-3">
        <p role="alert" className="text-sm text-destructive">
          Could not load the setup state.
        </p>
        <div>
          <Button variant="outline" onClick={() => void setupQuery.refetch()}>
            Try again
          </Button>
        </div>
      </div>
    );
  }

  const clamp = (index: number) => Math.min(Math.max(index, 0), steps.length - 1);

  // Stepper jumps are the wizard's own navigation, so it guards them; the
  // step callbacks do not re-check — Back was already confirmed by the
  // footer and advance follows a successful save, and the lifted dirty
  // flag can still be one render behind at that moment.
  const goTo = (index: number) => {
    if (dirty && !window.confirm(CONFIRM_MESSAGE)) return;
    setActiveIndex(clamp(index));
  };
  const moveTo = (index: number) => setActiveIndex(clamp(index));

  const completeCount = steps.filter((step) => step.complete).length;
  const percent = completeCount * 10;
  const activeStep = steps[activeIndex];
  const meta = STEP_META[activeStep.step_key];
  const ActiveStep = meta.Component;
  const isLast = activeIndex === steps.length - 1;

  return (
    <div className="mx-auto max-w-4xl">
      <header className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-4">
          <h1 className="text-xl font-bold tracking-tight text-foreground">
            Facility setup
          </h1>
          <p role="status" className="text-sm font-medium text-foreground">
            {percent}% complete
          </p>
        </div>
        <Progress value={percent} aria-label="Setup progress" />
      </header>

      <ol
        aria-label="Setup steps"
        className="mt-4 flex list-none flex-nowrap items-stretch gap-2 overflow-x-auto pb-1"
      >
        {steps.map((step, index) => (
          <li
            key={step.step_key}
            className="flex items-stretch whitespace-nowrap"
          >
            <button
              type="button"
              aria-current={index === activeIndex ? "step" : undefined}
              onClick={() => goTo(index)}
              className="flex items-center gap-2 rounded-md border bg-card px-3 py-1.5 text-sm font-medium text-foreground hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <span>
                {index + 1}. {STEP_META[step.step_key].label}
              </span>
              <Badge variant={step.complete ? "default" : "secondary"}>
                {step.complete ? "Complete" : "Incomplete"}
              </Badge>
            </button>
          </li>
        ))}
      </ol>

      <Card className="mt-4">
        <CardHeader>
          <h2
            ref={headingRef}
            tabIndex={-1}
            className="text-lg font-semibold tracking-tight text-card-foreground"
          >
            {meta.title}
          </h2>
        </CardHeader>
        <CardContent>
          <ActiveStep
            step={activeStep}
            onBack={activeIndex === 0 ? null : () => moveTo(activeIndex - 1)}
            onAdvance={() => moveTo(activeIndex + 1)}
            onDirtyChange={setDirty}
            isLast={isLast}
          />
        </CardContent>
      </Card>
    </div>
  );
}
