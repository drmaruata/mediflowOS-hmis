/**
 * DuplicateWarning — REG-003's pre-create surface: the probable duplicates
 * the duplicate-check returned, and the explicit "register anyway"
 * acknowledgement that must precede creating despite them.
 *
 * The check is advisory and the server does not block a create, so the
 * acknowledgement is the clerk's decision — and it is deliberately a
 * checkbox: Enter cannot confirm it implicitly (UI-002). A new check result
 * resets it, because a confirmation made for older candidates proves nothing
 * about the ones now on screen.
 */

import { Link } from "react-router-dom";

import { Label } from "@/components/ui/label";
import type { DuplicateCandidate } from "./patient.api";

interface DuplicateWarningProps {
  candidates: DuplicateCandidate[];
  acknowledged: boolean;
  onAcknowledgeChange: (acknowledged: boolean) => void;
}

export function DuplicateWarning({
  candidates,
  acknowledged,
  onAcknowledgeChange,
}: DuplicateWarningProps) {
  return (
    <section
      role="alert"
      aria-label="Possible duplicates"
      className="mt-4 rounded-md border border-destructive/50 bg-destructive/10 p-3"
    >
      <h3 className="text-sm font-semibold text-destructive">
        Possible existing patients
      </h3>
      <p className="mt-1 text-sm text-foreground">
        A registry check found patients who may be this person. Open their
        records to compare, or confirm below to register anyway.
      </p>
      <table className="mt-2 w-full text-sm">
        <caption className="sr-only">Possible existing patients</caption>
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th scope="col" className="px-2 py-2 font-medium">UHID</th>
            <th scope="col" className="px-2 py-2 font-medium">Name</th>
            <th scope="col" className="px-2 py-2 font-medium">Gender</th>
            <th scope="col" className="px-2 py-2 font-medium">Birth year</th>
            <th scope="col" className="px-2 py-2 font-medium">Mobile</th>
            <th scope="col" className="px-2 py-2 font-medium">Record</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((candidate) => (
            <tr key={candidate.id} className="border-b last:border-0">
              <td className="px-2 py-2 font-mono text-xs">{candidate.uhid}</td>
              <td className="px-2 py-2">{candidate.name}</td>
              <td className="px-2 py-2">{candidate.gender}</td>
              <td className="px-2 py-2">{candidate.year_of_birth ?? "—"}</td>
              <td className="px-2 py-2">{candidate.mobile_masked}</td>
              <td className="px-2 py-2">
                <Link
                  to={`/patients/${candidate.id}`}
                  className="text-primary underline-offset-4 hover:underline"
                >
                  Open
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex items-center gap-2">
        <input
          id="register-anyway"
          type="checkbox"
          className="size-4 rounded border-input accent-primary"
          checked={acknowledged}
          onChange={(event) => onAcknowledgeChange(event.target.checked)}
        />
        <Label htmlFor="register-anyway">
          These are different patients — register anyway
        </Label>
      </div>
    </section>
  );
}
