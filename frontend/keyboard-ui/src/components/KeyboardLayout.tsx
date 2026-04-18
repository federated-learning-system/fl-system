import { useCallback, useState, type MouseEvent } from "react";
import type { RoundState } from "../hooks/useKeyboardState";
import type { InferenceSource } from "../inference/inference_pipeline";

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

type RoundButtonState = "idle" | "starting" | "open" | "aggregating" | "done";

interface KeyboardLayoutProps {
  shiftActive: boolean;
  numbersActive: boolean;
  suggestions: [string, string, string];
  trainingBuffer: number;
  dpEpsilon: number;
  dpBudget: number;
  modelVersion: string;
  modelSource: InferenceSource;
  roundState: RoundState;
  onTypeChar: (char: string) => void;
  onBackspace: () => void;
  onEnter: () => void;
  onSpace: () => void;
  onToggleShift: () => void;
  onToggleNumbers: () => void;
  onSelectSuggestion: (index: number) => void;
  onStartRound?: () => void;
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

// ── Model source label ──────────────────────────────────────────────────────

const SOURCE_LABELS: Record<InferenceSource, string> = {
  loading: "loading\u2026",
  onnx: "onnx",
  server: "server",
  ngram: "ngram",
};

// ── Round button labels ──────────────────────────────────────────────────────

const ROUND_BTN_LABELS: Record<RoundButtonState, string> = {
  idle: "Start Round",
  starting: "Starting\u2026",
  open: "Round OPEN",
  aggregating: "Aggregating\u2026",
  done: "Done \u2713",
};

function mapRoundState(rs: RoundState): RoundButtonState {
  switch (rs) {
    case "OPEN": return "open";
    case "COLLECTING": return "aggregating";
    case "DONE": return "done";
    default: return "idle";
  }
}

export function KeyboardLayout({
  shiftActive,
  numbersActive,
  suggestions,
  trainingBuffer,
  dpEpsilon,
  dpBudget,
  modelVersion,
  modelSource,
  roundState,
  onTypeChar,
  onBackspace,
  onEnter,
  onSpace,
  onToggleShift,
  onToggleNumbers,
  onSelectSuggestion,
  onStartRound,
}: KeyboardLayoutProps) {
  const rows = numbersActive ? ROWS_NUMBERS : ROWS_ALPHA;
  const [pressedKey, setPressedKey] = useState<string | null>(null);
  const [roundBtnBusy, setRoundBtnBusy] = useState(false);

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
        {modelSource === "loading" && !suggestions.some(Boolean) ? (
          <div className="flex-1 flex items-center justify-center h-9 rounded-lg border border-border-dim bg-surface text-text-dim text-xs gap-2">
            <span className="inline-block w-3 h-3 border-2 border-accent/40 border-t-accent rounded-full suggestion-spinner" />
            Loading model...
          </div>
        ) : (
          suggestions.map((word, i) => (
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
          ))
        )}
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
          <span className="text-text-secondary">{trainingBuffer}</span> samples
        </span>

        <span className="text-text-dim">
          {"\u03B5"}{" "}
          <span className="text-text-secondary">
            {dpEpsilon.toFixed(2)}/{dpBudget.toFixed(2)}
          </span>
        </span>

        <span className="text-text-dim">
          <span className={`${modelSource === "loading" ? "text-round-collecting" : "text-accent-dim"}`}>
            {modelVersion}
          </span>
          <span className="text-text-dim ml-1">
            ({SOURCE_LABELS[modelSource]})
          </span>
        </span>

        <span className={`flex items-center gap-1 ${ROUND_COLORS[roundState]}`}>
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${ROUND_DOT_BG[roundState]} ${roundState === "COLLECTING" ? "glow-pulse" : ""}`}
          />
          {roundState}
        </span>
      </div>

      {/* ── Start Round button ── */}
      {onStartRound && (
        <button
          data-testid="start-round-btn"
          onClick={() => {
            if (roundBtnBusy || roundState === "OPEN" || roundState === "COLLECTING") return;
            setRoundBtnBusy(true);
            onStartRound();
            // Reset busy after brief delay (actual state comes via WebSocket/polling)
            setTimeout(() => setRoundBtnBusy(false), 2000);
          }}
          disabled={roundBtnBusy || roundState === "OPEN" || roundState === "COLLECTING"}
          className={`mt-1 w-full py-1.5 rounded-lg border text-[10px] tracking-wider font-[family-name:var(--font-display)] transition-all duration-200
            ${
              roundState === "OPEN" || roundState === "COLLECTING"
                ? "bg-surface border-round-collecting/30 text-round-collecting cursor-not-allowed"
                : roundState === "DONE"
                  ? "bg-round-done/10 border-round-done/30 text-round-done hover:bg-round-done/20 cursor-pointer"
                  : roundBtnBusy
                    ? "bg-surface border-accent/30 text-accent/60 cursor-wait"
                    : "bg-accent/8 border-accent/20 text-accent hover:bg-accent/15 hover:border-accent/40 cursor-pointer"
            }
          `}
        >
          {roundBtnBusy ? ROUND_BTN_LABELS.starting : ROUND_BTN_LABELS[mapRoundState(roundState)]}
        </button>
      )}
    </div>
  );
}
