/**
 * AuditLog — the compliance drill-down at /admin/audit (AUD-003; UI_UX §7
 * "Audit log viewer").
 *
 * The trail is read-only and tenant-scoped server-side; this screen adds no
 * edit or delete controls because none exist on the backend either
 * (AuditLogViewSet is a ReadOnlyModelViewSet). The filters are URL-driven
 * (?entity_type=&entity_id=, plus the page): the patient profile's "view
 * access history" action links in with them prefilled (AUD-003), a drilled
 * row's own button narrows to that entity, and the URL stays shareable
 * because the query params — not local state — drive the request. Entity
 * type is the table name (e.g. registry.patient) and entity id the row pk:
 * identifiers only, never PHI.
 */

import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ResourceSection } from "@/components/ResourceSection";
import { useSession } from "@/lib/session";
import { Pager } from "./Pager";
import { fetchAuditPage } from "./admin.api";

/**
 * Build the shareable filter URL. entity_id travels only beside entity_type
 * (the server applies it inside the type branch); page is omitted on page 1
 * so the canonical filtered URL stays short.
 */
function filterParams(
  entityType: string,
  entityId: string,
  page: number,
): URLSearchParams {
  const params = new URLSearchParams();
  if (entityType !== "") {
    params.set("entity_type", entityType);
    if (entityId !== "") params.set("entity_id", entityId);
  }
  if (page > 1) params.set("page", String(page));
  return params;
}

export default function AuditLog() {
  const session = useSession();
  const tenantId = session.data?.tenant_id ?? null;
  const [searchParams, setSearchParams] = useSearchParams();

  const entityType = searchParams.get("entity_type") ?? "";
  const entityId = searchParams.get("entity_id") ?? "";
  const pageParam = Number(searchParams.get("page") ?? "1");
  const page = Number.isInteger(pageParam) && pageParam >= 1 ? pageParam : 1;
  const filtered = entityType !== "";

  const events = useQuery({
    queryKey: ["audit", tenantId, entityType, entityId, page],
    queryFn: () => fetchAuditPage({ entityType, entityId, page }),
    enabled: tenantId !== null,
  });

  return (
    <div>
      <h2 className="text-xl font-bold tracking-tight text-card-foreground">Audit log</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Immutable record of access and change events. Filter by entity type (a
        table name, e.g. registry.patient) and entity id to answer “who opened
        this record?”.
      </p>

      {/* The key remounts the form whenever the URL's filters change
          externally (the drill-down button or the patient profile link), so
          the inputs always show the live filter without controlled-state
          plumbing. */}
      <form
        key={`${entityType}|${entityId}`}
        className="mt-3 flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          setSearchParams(
            filterParams(
              String(data.get("entity_type") ?? "").trim(),
              String(data.get("entity_id") ?? "").trim(),
              1,
            ),
          );
        }}
      >
        <div className="grid gap-1.5">
          <Label htmlFor="audit-entity-type">Entity type</Label>
          <Input
            id="audit-entity-type"
            name="entity_type"
            type="text"
            defaultValue={entityType}
            placeholder="registry.patient"
            className="max-w-xs"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="audit-entity-id">Entity id</Label>
          <Input
            id="audit-entity-id"
            name="entity_id"
            type="text"
            defaultValue={entityId}
            className="max-w-xs"
          />
        </div>
        <Button type="submit" variant="outline">
          Apply filters
        </Button>
        {filtered && (
          <Button
            type="button"
            variant="ghost"
            onClick={() => setSearchParams(new URLSearchParams())}
          >
            Clear filters
          </Button>
        )}
      </form>

      <ResourceSection
        title="Audit log"
        loading={events.isPending}
        rows={events.data?.results ?? []}
        rowKey={(row) => row.id}
        emptyText={
          filtered ? "No audit events for this entity." : "No audit events yet."
        }
        totalCount={events.data?.count ?? null}
        columns={[
          {
            key: "occurred_at",
            header: "Time",
            render: (row) => new Date(row.occurred_at).toLocaleString("en-IN"),
          },
          { key: "user_id", header: "Actor", render: (row) => row.user_id ?? "—" },
          { key: "action", header: "Action", render: (row) => row.action },
          {
            key: "entity",
            header: "Entity",
            render: (row) => `${row.entity_type} ${row.entity_id}`,
          },
          {
            key: "source",
            header: "Source",
            render: (row) => row.source ?? row.source_ip ?? "—",
          },
          { key: "reason", header: "Reason", render: (row) => row.reason ?? "—" },
          {
            key: "drill",
            header: "Filter",
            render: (row) => (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setSearchParams(filterParams(row.entity_type, row.entity_id, 1))
                }
              >
                Drill down
              </Button>
            ),
          },
        ]}
      >
        <Pager
          page={page}
          hasNext={Boolean(events.data?.next)}
          onPrev={() => setSearchParams(filterParams(entityType, entityId, page - 1))}
          onNext={() => setSearchParams(filterParams(entityType, entityId, page + 1))}
        />
      </ResourceSection>
    </div>
  );
}
