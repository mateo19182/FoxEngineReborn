import { useId } from "react";

export function DocTip({ text }: { text: string }) {
  const id = useId();
  return (
    <span className="doc-tip">
      <button
        type="button"
        className="doc-tip__btn"
        aria-describedby={id}
        aria-label="Documentation"
        title={text}
      >
        <span className="doc-tip__glyph" aria-hidden>
          i
        </span>
      </button>
      <span id={id} className="doc-tip__bubble" role="tooltip">
        {text}
      </span>
    </span>
  );
}
