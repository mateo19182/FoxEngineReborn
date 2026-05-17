import { useEffect, useId, useRef, useState } from "react";
import { DayPicker } from "react-day-picker";
import type { DateRange } from "react-day-picker";
import "react-day-picker/style.css";

type Props = {
  value: DateRange | undefined;
  onChange: (next: DateRange | undefined) => void;
};

const rangeLabelFmt = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

function formatRangeLabel(range: DateRange | undefined): string {
  if (!range?.from) return "All dates";
  const start = rangeLabelFmt.format(range.from);
  const endDay = range.to ?? range.from;
  const end = rangeLabelFmt.format(endDay);
  if (start === end) return start;
  return `${start} – ${end}`;
}

export function AuditDateRangeCalendar({ value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const panelId = useId();
  const triggerId = useId();

  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (e: MouseEvent) => {
      const el = rootRef.current;
      const t = e.target;
      if (!el || !(t instanceof Node)) return;
      if (!el.contains(t)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="audit-calendar-block" ref={rootRef}>
      <label className="audit-calendar-block__field-label" htmlFor={triggerId}>
        Date range
      </label>
      <button
        id={triggerId}
        type="button"
        className="audit-calendar-block__trigger"
        aria-expanded={open}
        aria-controls={panelId}
        aria-haspopup="dialog"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="audit-calendar-block__trigger-value">{formatRangeLabel(value)}</span>
        <span className="audit-calendar-block__chevron" aria-hidden />
      </button>
      {open ? (
        <div className="audit-calendar-block__popover" id={panelId} role="dialog" aria-label="Choose date range">
          <div className="audit-calendar-block__picker">
            <DayPicker mode="range" selected={value} onSelect={onChange} />
          </div>
          <div className="audit-calendar-block__popover-foot">
            <button
              type="button"
              className="secondary"
              onClick={() => onChange(undefined)}
              disabled={!value?.from}
            >
              Clear dates
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
