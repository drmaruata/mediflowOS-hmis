/**
 * Pager — Previous/Next controls over the backend's fixed-size pages
 * (PageNumberPagination, PAGE_SIZE 50 with no client page-size control).
 * The row tables stay honest through ResourceSection's "Showing X of Y"
 * caption; this adds page walking for the lists that outgrow one page.
 */

import { Button } from "@/components/ui/button";

export interface PagerProps {
  page: number;
  hasNext: boolean;
  onPrev: () => void;
  onNext: () => void;
}

export function Pager({ page, hasNext, onPrev, onNext }: PagerProps) {
  return (
    <div className="mt-2 flex items-center gap-3">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onPrev}
        disabled={page <= 1}
      >
        Previous page
      </Button>
      <span className="text-sm text-muted-foreground">Page {page}</span>
      <Button type="button" variant="outline" size="sm" onClick={onNext} disabled={!hasNext}>
        Next page
      </Button>
    </div>
  );
}
