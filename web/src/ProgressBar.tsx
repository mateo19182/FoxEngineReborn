type ProgressBarProps = {
  /** 0–100 when determinate; omit for indeterminate while active */
  value?: number | null;
  indeterminate?: boolean;
  label?: string;
  className?: string;
};

export function ProgressBar({ value, indeterminate, label, className }: ProgressBarProps) {
  const isIndeterminate = indeterminate || value == null;
  const clamped =
    value != null ? Math.min(100, Math.max(0, Math.round(value))) : undefined;

  return (
    <div className={className ? `progress-bar ${className}` : "progress-bar"}>
      {label ? <span className="progress-bar__label">{label}</span> : null}
      <div
        className={`progress-bar__track${isIndeterminate ? " progress-bar__track--indeterminate" : ""}`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={isIndeterminate ? undefined : clamped}
        aria-label={label}
      >
        <div
          className="progress-bar__fill"
          style={isIndeterminate ? undefined : { width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}
