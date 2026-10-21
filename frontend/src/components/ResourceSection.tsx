/**
 * ResourceSection — the shared read-only table shell the wizard's CRUD steps
 * (departments/wards/beds, service units, staff positions, reference data,
 * baseline inputs) and the patient registry's list surfaces compose around.
 * Rows live behind their own endpoints, so the section only renders what a
 * query already fetched; the children slot holds a screen's own form or
 * notes.
 *
 * A plain semantic <table> (the doc's Table component is not vendored):
 * caption names the table for role-based queries, th scope=col, and the
 * loading/empty states are explicit text — never a silently blank area.
 * The list endpoints paginate at the backend's fixed page size, so when the
 * tenant-wide `count` exceeds the rendered rows a visible caption states the
 * truncation — a short table must never masquerade as the whole list.
 */

import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
}

interface ResourceSectionProps<T> {
  title: string;
  loading: boolean;
  rows: T[];
  columns: Array<Column<T>>;
  rowKey: (row: T) => string;
  emptyText: string;
  /** Tenant-wide total from the paginated `count`; the caption renders only when it exceeds the rows shown. */
  totalCount?: number | null;
  /** The owning screen's add-form (fields + its own submit button + error alert) or notes. */
  children?: ReactNode;
}

export function ResourceSection<T>({
  title,
  loading,
  rows,
  columns,
  rowKey,
  emptyText,
  totalCount,
  children,
}: ResourceSectionProps<T>) {
  const truncated =
    totalCount !== undefined && totalCount !== null && totalCount > rows.length;
  return (
    <section aria-label={title} className="mt-6 first:mt-0">
      <h3 className="text-base font-semibold text-card-foreground">{title}</h3>
      <table className="mt-2 w-full text-sm">
        <caption className="sr-only">{title}</caption>
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            {columns.map((column) => (
              <th key={column.key} scope="col" className="px-2 py-2 font-medium">
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td className="px-2 py-2 text-muted-foreground" colSpan={columns.length}>
                Loading…
              </td>
            </tr>
          ) : rows.length === 0 ? (
            <tr>
              <td className="px-2 py-2 text-muted-foreground" colSpan={columns.length}>
                {emptyText}
              </td>
            </tr>
          ) : (
            rows.map((row) => (
              <tr key={rowKey(row)} className="border-b last:border-0">
                {columns.map((column) => (
                  <td key={column.key} className="px-2 py-2">
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
      {truncated && (
        <p className="mt-1 text-sm text-muted-foreground">
          Showing {rows.length} of {totalCount}
        </p>
      )}
      {children}
    </section>
  );
}
