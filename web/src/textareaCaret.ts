/** Viewport coordinates for a caret index inside a textarea. */
export function getTextareaCaretClientRect(
  textarea: HTMLTextAreaElement,
  position: number,
): { top: number; left: number } {
  const style = window.getComputedStyle(textarea);
  const textareaRect = textarea.getBoundingClientRect();

  const mirror = document.createElement("div");
  const s = mirror.style;
  s.position = "fixed";
  s.top = `${textareaRect.top}px`;
  s.left = `${textareaRect.left}px`;
  s.width = style.width;
  s.height = style.height;
  s.padding = style.padding;
  s.border = style.border;
  s.boxSizing = style.boxSizing;
  s.overflow = "auto";
  s.visibility = "hidden";
  s.whiteSpace = style.whiteSpace === "normal" ? "pre-wrap" : style.whiteSpace;
  s.wordWrap = "break-word";
  s.overflowWrap = style.overflowWrap;
  s.fontFamily = style.fontFamily;
  s.fontSize = style.fontSize;
  s.fontWeight = style.fontWeight;
  s.fontStyle = style.fontStyle;
  s.letterSpacing = style.letterSpacing;
  s.lineHeight = style.lineHeight;
  s.tabSize = style.tabSize;

  const before = textarea.value.slice(0, position);
  const after = textarea.value.slice(position) || ".";

  mirror.textContent = before;
  const marker = document.createElement("span");
  marker.textContent = after[0] === "\n" ? " " : after[0]!;
  mirror.appendChild(marker);

  document.body.appendChild(mirror);
  mirror.scrollTop = textarea.scrollTop;
  mirror.scrollLeft = textarea.scrollLeft;

  const markerRect = marker.getBoundingClientRect();
  document.body.removeChild(mirror);

  return { top: markerRect.top, left: markerRect.left };
}
