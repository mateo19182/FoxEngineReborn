import { useMemo } from "react";
import { createPortal } from "react-dom";

import {
  type DslFamilyOption,
  type DslFieldSpec,
  type DslTagOption,
} from "./dslAutocomplete";
import { visibleSuggestionRange } from "./dslSuggestionWindow";
import { useDslAutocompleteMenu } from "./useDslAutocompleteMenu";

type DslTextareaProps = {
  id: string;
  value: string;
  onChange: (value: string) => void;
  onRun?: () => void;
  rows?: number;
  required?: boolean;
  tags: DslTagOption[];
  families: DslFamilyOption[];
  fields: DslFieldSpec[];
};

export function DslTextarea({
  id,
  value,
  onChange,
  onRun,
  rows = 4,
  required,
  tags,
  families,
  fields,
}: DslTextareaProps) {
  const {
    textareaRef,
    menuOpen,
    activeIndex,
    setActiveIndex,
    menuPos,
    suggestions,
    activeSuggestion,
    syncCursorFromTarget,
    acceptSuggestion,
    updateMenuPosition,
    focused,
    focusMenu,
    blurMenu,
    closeMenu,
  } = useDslAutocompleteMenu({ value, onChange, tags, families, fields });

  const showAutocomplete = focused && menuOpen && suggestions.length > 0;

  const { start: visibleStart, end: visibleEnd } = useMemo(
    () => visibleSuggestionRange(suggestions.length, activeIndex),
    [suggestions.length, activeIndex],
  );
  const visibleSuggestions = suggestions.slice(visibleStart, visibleEnd);

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      onRun?.();
      return;
    }

    if (!showAutocomplete) return;

    if (e.key === "Tab") {
      e.preventDefault();
      const pick = suggestions[activeIndex] ?? suggestions[0];
      if (pick) acceptSuggestion(pick);
      return;
    }

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (i + 1) % suggestions.length);
      return;
    }

    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => (i - 1 + suggestions.length) % suggestions.length);
      return;
    }

    if (e.key === "Escape") {
      e.preventDefault();
      closeMenu();
    }
  }

  const menu =
    showAutocomplete && menuPos
      ? createPortal(
          <div
            id={`${id}-ac-menu`}
            className="dsl-autocomplete__menu"
            role="listbox"
            style={{ top: menuPos.top, left: menuPos.left }}
            onWheel={(event) => {
              if (suggestions.length <= 1) return;
              event.preventDefault();
              if (event.deltaY > 0) {
                setActiveIndex((i) => (i + 1) % suggestions.length);
              } else if (event.deltaY < 0) {
                setActiveIndex((i) => (i - 1 + suggestions.length) % suggestions.length);
              }
            }}
          >
            {visibleSuggestions.map((item, offset) => {
              const index = visibleStart + offset;
              return (
                <button
                  key={`${index}-${item.label}`}
                  type="button"
                  role="option"
                  aria-selected={index === activeIndex}
                  className={
                    index === activeIndex
                      ? "dsl-autocomplete__option dsl-autocomplete__option--active"
                      : "dsl-autocomplete__option"
                  }
                  onMouseDown={(event) => {
                    event.preventDefault();
                    acceptSuggestion(item);
                  }}
                  onMouseEnter={() => setActiveIndex(index)}
                >
                  <code className="mono">{item.label}</code>
                </button>
              );
            })}
          </div>,
          document.body,
        )
      : null;

  return (
    <div className="dsl-autocomplete">
      <textarea
        ref={textareaRef}
        id={id}
        rows={rows}
        value={value}
        required={required}
        autoComplete="off"
        spellCheck={false}
        aria-autocomplete="list"
        aria-controls={showAutocomplete ? `${id}-ac-menu` : undefined}
        aria-expanded={showAutocomplete}
        onChange={(e) => {
          onChange(e.target.value);
          syncCursorFromTarget(e.target);
        }}
        onKeyDown={handleKeyDown}
        onKeyUp={(e) => syncCursorFromTarget(e.currentTarget)}
        onClick={(e) => syncCursorFromTarget(e.currentTarget)}
        onSelect={(e) => syncCursorFromTarget(e.currentTarget)}
        onFocus={(e) => {
          focusMenu();
          syncCursorFromTarget(e.currentTarget);
        }}
        onScroll={updateMenuPosition}
        onBlur={blurMenu}
      />
      {menu}
      {focused && activeSuggestion ? (
        <p className="dsl-autocomplete__preview muted" aria-live="polite">
          <span className="dsl-autocomplete__preview-label">Tab</span>{" "}
          <code className="mono">{activeSuggestion.insert}</code>
          {onRun ? (
            <>
              {" "}
              · <span className="dsl-autocomplete__preview-label">Ctrl+Enter</span> run
            </>
          ) : null}
        </p>
      ) : focused && onRun ? (
        <p className="dsl-autocomplete__preview muted">
          <span className="dsl-autocomplete__preview-label">Ctrl+Enter</span> run query
        </p>
      ) : null}
    </div>
  );
}
