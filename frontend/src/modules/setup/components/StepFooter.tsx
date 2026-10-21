/**
 * StepFooter — the wizard's Back/Save/Next chrome plus the three behaviours
 * UI_UX §7 puts on it: Ctrl+S saves, Back and a table step's Next ask before
 * discarding a dirty step, and failures render as explicit alerts
 * (permission refusals name the claim the server gated on) rather than
 * silent no-ops.
 *
 * Form steps render the footer inside their <form>, so Next is the submit
 * button and Enter anywhere in the form does what Next does (UI-002). Only
 * the active step is mounted, so exactly one Ctrl+S listener exists at a
 * time; the effect is symmetric for StrictMode's double mount.
 */

import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/apiClient";
import { extractServerErrors } from "../setup.api";
import type { SetupStep } from "../setup.api";

export interface StepComponentProps {
  step: SetupStep;
  /** Null on the first step: Back renders disabled, never absent. */
  onBack: (() => void) | null;
  onAdvance: () => void;
  /** Lifts the step's dirty flag so the wizard can guard navigation. */
  onDirtyChange: (dirty: boolean) => void;
  isLast: boolean;
}

/**
 * Reports the step's dirty flag to the wizard for as long as the step is
 * mounted; the cleanup clears it so a step unmounting cannot leave the
 * wizard guarding a form that no longer exists.
 */
export function useStepDirtyBridge(
  isDirty: boolean,
  onDirtyChange: (dirty: boolean) => void,
): void {
  useEffect(() => {
    onDirtyChange(isDirty);
    return () => onDirtyChange(false);
  }, [isDirty, onDirtyChange]);
}

/**
 * The failure surface for a step's save or row mutation: a 403 from a
 * claim-gated endpoint names the claim the server gated on
 * (WritePermissionMixin), a 403 from the MFA gate surfaces the server's own
 * instruction instead (it carries code "mfa_required"; common/mfa.py) — the
 * two must never be confused — and surfaces without a claim (the config
 * viewsets gate writes on no permission) render the server's detail.
 * 400s surface the server's own message, anything else is an honest retry
 * suggestion. Never a spinner that never ends and never a silent drop.
 */
export function StepAlert({ error, claim }: { error: unknown; claim?: string }) {
  if (error === null || error === undefined) return null;
  if (error instanceof ApiError && error.status === 403) {
    const { fieldErrors, general } = extractServerErrors(error);
    // The MFA body is {detail, code: "mfa_required"} and the parser parks
    // the code key in fieldErrors — that is how the gate is told apart from
    // a claim refusal, which carries only detail.
    if (claim !== undefined && fieldErrors.code !== "mfa_required") {
      return (
        <p
          role="alert"
          className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          Saving requires the {claim} permission. Your changes were not saved.
        </p>
      );
    }
    return (
      <p
        role="alert"
        className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
      >
        {general ?? "The server refused this change; nothing was saved."}
      </p>
    );
  }
  const { general } = extractServerErrors(error);
  if (general === null) return null;
  return (
    <p
      role="alert"
      className="rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive"
    >
      {general}
    </p>
  );
}

interface StepFooterProps {
  onBack: (() => void) | null;
  dirty: boolean;
  /** Draft save (status in_progress): the Ctrl+S target. */
  onSave: () => void;
  saving: boolean;
  saved: boolean;
  error: unknown;
  /** The permission the server's PUT gate names in a 403. */
  claim: string;
  nextLabel: string;
  /**
   * Table steps have no outer <form> (each add-form is its own form, so
   * Enter adds the row in focus instead of finishing the step); they pass
   * the advance handler and Next is a plain button. Form steps leave this
   * undefined so Next is the form's submit button — Enter submits the step.
   */
  onNext?: () => void;
}

const CONFIRM_MESSAGE = "Discard unsaved changes to this step?";

export function StepFooter({
  onBack,
  dirty,
  onSave,
  saving,
  saved,
  error,
  claim,
  nextLabel,
  onNext,
}: StepFooterProps) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        onSave();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onSave]);

  const goBack = () => {
    if (dirty && !window.confirm(CONFIRM_MESSAGE)) return;
    onBack?.();
  };

  // Table steps only reach this (form steps submit instead): Next must not
  // silently discard a half-typed add-form — the same guard as Back.
  const goNext = () => {
    if (dirty && !window.confirm(CONFIRM_MESSAGE)) return;
    onNext?.();
  };

  return (
    <>
      <StepAlert error={error} claim={claim} />
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={goBack}
            disabled={onBack === null}
          >
            Back
          </Button>
          {saved && !dirty && (
            <p role="status" className="text-sm text-muted-foreground">
              Step saved.
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <Button type="button" variant="secondary" onClick={onSave} disabled={saving}>
            Save
          </Button>
          {onNext === undefined ? (
            <Button type="submit" disabled={saving}>
              {nextLabel}
            </Button>
          ) : (
            <Button type="button" onClick={goNext} disabled={saving}>
              {nextLabel}
            </Button>
          )}
        </div>
      </div>
    </>
  );
}
