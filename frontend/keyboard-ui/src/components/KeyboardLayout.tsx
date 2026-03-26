import { useCallback, useState, type MouseEvent } from "react";
import type { RoundState } from "../hooks/useKeyboardState";

// ── Key layouts ──────────────────────────────────────────────────────────────

const ROWS_ALPHA = [
  ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
  ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
  ["z", "x", "c", "v", "b", "n", "m"],
];

const ROWS_NUMBERS = [
  ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
  ["@", "#", "$", "%", "&", "-", "+", "(", ")"],
  ["*", '"', "'", ":", ";", "!", "?"],
];

// ── Types ────────────────────────────────────────────────────────────────────

interface KeyboardLayoutProps {
  shiftActive: boolean;
  numbersActive: boolean;
  suggestions: [string, string, string];
  trainingBuffer: number;
  dpEpsilon: number;
  dpBudget: number;
  modelVersion: string;
  roundState: RoundState;
  onTypeChar: (char: string) => void;
  onBackspace: () => void;
  onEnter: () => void;
  onSpace: () => void;
  onToggleShift: () => void;
  onToggleNumbers: () => void;
  onSelectSuggestion: (index: number) => void;
}

// ── Round state styling ──────────────────────────────────────────────────────

const ROUND_COLORS: Record<RoundState, string> = {
  IDLE: "text-text-dim",
  OPEN: "text-round-open",
  COLLECTING: "text-round-collecting",
  DONE: "text-round-done",
};

const ROUND_DOT_BG: Record<RoundState, string> = {
  IDLE: "bg-text-dim",
  OPEN: "bg-round-open",
  COLLECTING: "bg-round-collecting",
  DONE: "bg-round-done",
};

// ── Component ────────────────────────────────────────────────────────────────

export function KeyboardLayout({
  shiftActive,
  numbersActive,
  suggestions,
  trainingBuffer,
  dpEpsilon,
  dpBudget,
  modelVersion,
  roundState,
  onTypeChar,
  onBackspace,
  onEnter,
  onSpace,
  onToggleShift,
  onToggleNumbers,
  onSelectSuggestion,
}: KeyboardLayoutProps) {
  const rows = numbersActive ? ROWS_NUMBERS : ROWS_ALPHA;
  const [pressedKey, setPressedKey] = useState<string | null>(null);

  const handleKey = useCallback(
    (key: string, handler: () => void) => (e: MouseEvent) => {
      e.preventDefault();
      setPressedKey(key);
      handler();
      setTimeout(() => setPressedKey(null), 150);
    },
    []
  );

  const keyBase =
    "flex items-center justify-center rounded-lg text-sm font-medium select-none cursor-pointer transition-colors duration-75 border border-border-dim";
  const keyNormal = `${keyBase} bg-surface-key hover:bg-surface-key-active active:bg-accent active:text-void h-11`;
  const keySpecial = `${keyBase} bg-surface-raised hover:bg-surface-key-active active:bg-accent active:text-void h-11 text-text-secondary text-xs`;

  return (
    <div className="flex flex-col gap-2 px-2 pb-2 pt-0 bg-surface border-t border-border-dim">
      {/* ── Suggestion bar ── */}
      <div
        data-testid="suggestion-bar"
        className="flex gap-2 px-1 py-1.5"
      >
        {suggestions.map((word, i) => (
          <button
            key={i}
            data-testid={`suggestion-${i}`}
            onClick={() => onSelectSuggestion(i)}
            className={`flex-1 h-9 rounded-lg border text-sm font-[family-name:var(--font-display)] transition-all duration-150
              ${
                word
                  ? "bg-pill-bg border-pill-border text-text-primary hover:border-accent hover:text-accent hover:shadow-[0_0_12px_rgba(58,255,180,0.12)]"
                  : "bg-surface border-border-dim text-text-dim cursor-default"
              }
            `}
          >
            {word || "\u00B7\u00B7\u00B7"}
          </button>
        ))}
      </div>

      {/* ── Key rows ── */}
      {rows.map((row, ri) => (
        <div key={ri} className="flex justify-center gap-[5px]">
          {/* Shift / symbol toggle on last letter row */}
          {ri === 2 && !numbersActive && (
            <button
              data-testid="shift-key"
              onMouseDown={handleKey("shift", onToggleShift)}
              className={`${keySpecial} w-12 ${shiftActive ? "!bg-accent !text-void !border-accent" : ""}`}
            >
              {shiftActive ? (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 3l-8 9h5v8h6v-8h5z" />
                </svg>
              ) : (
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 3l-8 9h5v8h6v-8h5z" />
                </svg>
              )}
            </button>
          )}

          {ri === 2 && numbersActive && (
            <div className="w-12" /> /* spacer */
          )}

          {row.map((key) => {
            const display = !numbersActive && shiftActive ? key.toUpperCase() : key;
            return (
              <button
                key={key}
                data-testid={`key-${key}`}
                onMouseDown={handleKey(key, () => onTypeChar(key))}
                className={`${keyNormal} w-[9%] max-w-[36px] ${pressedKey === key ? "key-pressed" : ""}`}
              >
                {display}
              </button>
            );
          })}

          {/* Backspace on last row */}
          {ri === 2 && (
            <button
              data-testid="backspace-key"
              onMouseDown={handleKey("backspace", onBackspace)}
              className={`${keySpecial} w-12`}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M21 4H8l-7 8 7 8h13a2 2 0 002-2V6a2 2 0 00-2-2z" />
                <line x1="18" y1="9" x2="12" y2="15" />
                <line x1="12" y1="9" x2="18" y2="15" />
              </svg>
            </button>
          )}
        </div>
      ))}

      {/* ── Bottom row: numbers toggle, space, enter ── */}
      <div className="flex gap-[5px] justify-center">
        <button
          data-testid="numbers-key"
          onMouseDown={handleKey("123", onToggleNumbers)}
          className={`${keySpecial} w-14 ${numbersActive ? "!bg-accent !text-void !border-accent" : ""}`}
        >
          {numbersActive ? "ABC" : "123"}
        </button>

        <button
          data-testid="space-key"
          onMouseDown={handleKey("space", onSpace)}
          className={`${keyNormal} flex-1 text-xs text-text-dim tracking-[0.2em]`}
        >
          FLS
        </button>

        <button
          data-testid="enter-key"
          onMouseDown={handleKey("enter", onEnter)}
          className={`${keySpecial} w-16 !bg-accent/20 !text-accent !border-accent/30 hover:!bg-accent/30`}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M9 10l-5 5 5 5" />
            <path d="M20 4v7a4 4 0 01-4 4H4" />
          </svg>
        </button>
      </div>

      {/* ── Status bar ── */}
      <div
        data-testid="status-bar"
        className="flex items-center justify-between px-3 py-2 mt-1 rounded-lg bg-surface-raised border border-border-dim text-[10px] tracking-wide"
      >
        <span className="text-text-dim">
          Training buffer:{" "}
          <span className="text-text-secondary">{trainingBuffer} samples</span>
        </span>

        <span className="text-text-dim">
          DP {"\u03B5"}:{" "}
          <span className="text-text-secondary">
            {dpEpsilon.toFixed(2)}/{dpBudget.toFixed(2)}
          </span>
        </span>

        <span className="text-text-dim">
          Model:{" "}
          <span className="text-accent-dim">{modelVersion}</span>
        </span>

        <span className={`flex items-center gap-1 ${ROUND_COLORS[roundState]}`}>
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${ROUND_DOT_BG[roundState]} ${roundState === "COLLECTING" ? "glow-pulse" : ""}`}
          />
          {roundState}
        </span>
      </div>
    </div>
  );
}
