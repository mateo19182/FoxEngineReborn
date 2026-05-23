import { useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  analyzeDslAtCursor,
  applyDslSuggestion,
  getDslSuggestions,
  type DslCompletionContext,
  type DslFamilyOption,
  type DslFieldSpec,
  type DslSuggestion,
  type DslTagOption,
} from "./dslAutocomplete";
import { getTextareaCaretClientRect } from "./textareaCaret";

type UseDslAutocompleteMenuArgs = {
  value: string;
  onChange: (value: string) => void;
  tags: DslTagOption[];
  families: DslFamilyOption[];
  fields: DslFieldSpec[];
};

export function useDslAutocompleteMenu({
  value,
  onChange,
  tags,
  families,
  fields,
}: UseDslAutocompleteMenuArgs) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [focused, setFocused] = useState(false);
  const [cursor, setCursor] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [menuPos, setMenuPos] = useState<{ top: number; left: number } | null>(null);
  const pendingCursorRef = useRef<number | null>(null);

  const completionCtx: DslCompletionContext | null = analyzeDslAtCursor(value, cursor);
  const suggestions =
    completionCtx && fields.length > 0
      ? getDslSuggestions(completionCtx, { tags, families, fields }, value)
      : [];

  const activeSuggestion: DslSuggestion | null =
    menuOpen && suggestions.length > 0 ? (suggestions[activeIndex] ?? suggestions[0] ?? null) : null;

  useEffect(() => {
    if (!menuOpen) return;
    setActiveIndex(0);
  }, [completionCtx?.kind, completionCtx?.prefix, completionCtx?.field, menuOpen]);

  useEffect(() => {
    if (!focused || suggestions.length === 0) {
      setMenuOpen(false);
      return;
    }
    setMenuOpen(true);
  }, [focused, suggestions]);

  useLayoutEffect(() => {
    const el = textareaRef.current;
    if (!menuOpen || suggestions.length === 0 || !el) {
      setMenuPos(null);
      return;
    }
    setMenuPos(getTextareaCaretClientRect(el, cursor));
  }, [menuOpen, suggestions.length, cursor, value]);

  useEffect(() => {
    const next = pendingCursorRef.current;
    if (next === null) return;
    pendingCursorRef.current = null;
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(next, next);
    setCursor(next);
  }, [value]);

  function syncCursorFromTarget(target: HTMLTextAreaElement) {
    setCursor(target.selectionStart ?? 0);
  }

  function acceptSuggestion(suggestion: DslSuggestion) {
    if (!completionCtx) return;
    const { next, cursor: nextCursor } = applyDslSuggestion(value, suggestion, completionCtx);
    pendingCursorRef.current = nextCursor;
    onChange(next);
    setMenuOpen(false);
  }

  function updateMenuPosition() {
    const el = textareaRef.current;
    if (!el || !menuOpen || suggestions.length === 0) return;
    setMenuPos(getTextareaCaretClientRect(el, cursor));
  }

  function closeMenu() {
    setMenuOpen(false);
  }

  function focusMenu() {
    setFocused(true);
  }

  function blurMenu() {
    setFocused(false);
    closeMenu();
  }

  return {
    textareaRef,
    focused,
    focusMenu,
    blurMenu,
    menuOpen,
    activeIndex,
    setActiveIndex,
    menuPos,
    suggestions,
    activeSuggestion,
    completionCtx,
    syncCursorFromTarget,
    acceptSuggestion,
    updateMenuPosition,
    closeMenu,
  };
}
