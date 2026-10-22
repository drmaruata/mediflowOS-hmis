/**
 * OpSlip — print-optimised OP slip view (UI-006, HW-001).
 *
 * Route: /print/op-slip/:visitId — no app chrome, no nav, no header.
 * Fetches GET /api/v1/visits/{visitId}/op-slip/ (OpSlipView).
 * Renders patient UHID, name, token, department, facility, dates, and QR of UHID.
 * Print button calls window.print(). Print CSS in src/styles/print.css handles
 * @media print for 80mm thermal and A4.
 */

import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import {
  Button,
} from "@/components/ui/button";
import { apiClient } from "@/lib/apiClient";
import "@/styles/print.css";
import "./OpSlip.css";

export interface OpSlipToken {
  readonly series: string;
  readonly number: number;
}

export interface OpSlipPayload {
  readonly uhid: string;
  readonly patient_name: string;
  readonly token: OpSlipToken | null;
  readonly department: string;
  readonly facility: string;
  readonly issued_at: string | null;
  readonly visit_date: string;
}

const SLIP_QUERY_KEY = (visitId: string) => ["op-slip", visitId];

async function fetchOpSlip(visitId: string): Promise<OpSlipPayload> {
  return apiClient<OpSlipPayload>(`/api/v1/visits/${visitId}/op-slip/`);
}

function formatToken(token: OpSlipToken | null): string {
  if (!token) return "Not issued";
  return `${token.series}-${String(token.number).padStart(3, "0")}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="op-slip-error" role="alert">
      <div className="op-slip-error-content">
        <h1 className="op-slip-error-title">Unable to load OP slip</h1>
        <p className="op-slip-error-message">{message}</p>
      </div>
    </div>
  );
}

function PrintButton({ onPrint }: { onPrint: () => void }) {
  return (
    <Button
      type="button"
      onClick={onPrint}
      className="op-slip-print-button no-print"
      aria-label="Print OP slip"
    >
      <svg
        className="size-4"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M6 9V2h12v7" />
        <path d="M6 18H4a2 2 0 0 1-2-2v-5" />
        <path d="M18 18h2a2 2 0 0 0 2-2v-5" />
        <rect x="6" y="14" width="12" height="8" rx="1" />
      </svg>
      <span>Print</span>
    </Button>
  );
}

function QrCode({ payload }: { payload: string }) {
  // Minimal QR code using a data URI for a pre-generated QR SVG.
  // KNOWN LIMITATION (HW-001): This renders a text placeholder, not a scannable QR code.
  // A real QR library (e.g., qrcode.react) should replace this in a future task.
  // The payload is the UHID (QRCodeViewSet._encode_data format is HIP[-counter][-department_id]
  // but for a patient-facing slip we encode the UHID directly).
  const qrSvg = `data:image/svg+xml;base64,${btoa(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
      <rect width="100" height="100" fill="white"/>
      <text x="50" y="55" font-family="monospace" font-size="8" text-anchor="middle" fill="black">${payload}</text>
      <text x="50" y="65" font-family="monospace" font-size="6" text-anchor="middle" fill="#666">QR: ${payload}</text>
    </svg>`
  )}`;

  return (
    <img
      data-testid="op-slip-qr"
      data-qr-payload={payload}
      src={qrSvg}
      alt={`QR code for ${payload}`}
      className="op-slip-qr"
      aria-hidden="true"
    />
  );
}

export default function OpSlip() {
  const { visitId } = useParams<{ visitId: string }>();
  const visitIdParam = visitId ?? "";

  const { data, isLoading, isError, error } = useQuery({
    queryKey: SLIP_QUERY_KEY(visitIdParam),
    queryFn: () => fetchOpSlip(visitIdParam),
    enabled: visitIdParam !== "",
    retry: false,
  });

  // Set data-print class on document root for print CSS
  useEffect(() => {
    document.documentElement.setAttribute("data-print", "true");
    return () => {
      document.documentElement.removeAttribute("data-print");
    };
  }, []);

  const handlePrint = () => {
    window.print();
  };

  if (visitIdParam === "") {
    return (
      <ErrorState message="Visit ID is required." />
    );
  }

  if (isLoading) {
    return (
      <div className="op-slip-loading" role="status" aria-busy="true">
        <p>Loading OP slip…</p>
      </div>
    );
  }

  if (isError) {
    const apiError = error as { status?: number; message?: string };
    const status = apiError?.status;
    let message = "Unable to load OP slip.";
    if (status === 401) {
      message = "Please sign in to print the OP slip.";
    } else if (status === 404) {
      message = "Visit not found.";
    } else if (apiError?.message) {
      // apiClient.ApiError.message contains the response text; try to extract detail
      try {
        const parsed = JSON.parse(apiError.message);
        if (parsed.detail && typeof parsed.detail === "string") {
          message = parsed.detail;
        }
      } catch {
        message = apiError.message;
      }
    }
    return <ErrorState message={message} />;
  }

  if (!data) {
    return <ErrorState message="No data returned." />;
  }

  const slip = data;

  return (
    <div className="op-slip-page">
      <PrintButton onPrint={handlePrint} />

      <div className="op-slip-sheet" role="document">
        <header className="op-slip-header">
          <div className="op-slip-facility">
            <h1 className="op-slip-facility-name">{slip.facility}</h1>
            <p className="op-slip-facility-subtitle">Outpatient Slip</p>
          </div>
          <QrCode payload={slip.uhid} />
        </header>

        <div className="op-slip-body">
          <section className="op-slip-section">
            <h2 className="op-slip-section-title">Patient</h2>
            <dl className="op-slip-fields">
              <div className="op-slip-field">
                <dt>UHID</dt>
                <dd className="op-slip-uhid">{slip.uhid}</dd>
              </div>
              <div className="op-slip-field">
                <dt>Name</dt>
                <dd>{slip.patient_name}</dd>
              </div>
            </dl>
          </section>

          <section className="op-slip-section">
            <h2 className="op-slip-section-title">Visit</h2>
            <dl className="op-slip-fields">
              <div className="op-slip-field">
                <dt>Department</dt>
                <dd>{slip.department}</dd>
              </div>
              <div className="op-slip-field">
                <dt>Date</dt>
                <dd>{slip.visit_date}</dd>
              </div>
              <div className="op-slip-field">
                <dt>Token</dt>
                <dd className="op-slip-token">{formatToken(slip.token)}</dd>
              </div>
              <div className="op-slip-field">
                <dt>Issued at</dt>
                <dd>{formatDate(slip.issued_at)}</dd>
              </div>
            </dl>
          </section>
        </div>

        <footer className="op-slip-footer no-print">
          <p>This slip is valid for the visit date shown above.</p>
        </footer>
      </div>
    </div>
  );
}