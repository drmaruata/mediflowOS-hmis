/**
 * ResourceSection — the shared read-only table shell the wizard's CRUD steps
 * (departments/wards/beds, service units, staff positions, reference data,
 * baseline inputs) compose around. Rows live in their own tables behind
 * their own endpoints, so the section only renders what a query already
 * fetched; the add-form slot is the step's own controlled form.
 *
 * A plain semantic <table> (the doc's Table component is not vendored):
 * caption names the table for role-based queries, th scope=col, and the
 * loading/empty states are explicit text — never a silently blank area.
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
  /** The step's add-form (fields + its own submit button + error alert). */
  children?: ReactNode;
}

export function ResourceSection<T>({
  title,
  loading,
  rows,
  columns,
  rowKey,
  emptyText,
  children,
}: ResourceSectionProps<T>) {
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
      {children}
    </section>
  );
}
