/**
 * inference/ngram_fallback.ts
 *
 * Bigram-based fallback for next-word suggestions when the ONNX model is
 * unavailable (cold start, network issues, WASM loading).
 *
 * Loads public/models/bigrams.json (~100KB) — a map of word → top completions.
 */

export interface BigramEntry {
  /** Next words sorted by descending frequency */
  next: string[];
}

/** word → top completions */
type BigramTable = Record<string, string[]>;

let bigramTable: BigramTable | null = null;
let loadPromise: Promise<void> | null = null;

/** Default fallback when no context matches */
const DEFAULT_SUGGESTIONS: [string, string, string] = ["the", "I", "a"];

/**
 * Load bigrams.json from public/models/.
 * Safe to call multiple times — deduplicates.
 */
export function loadBigrams(): Promise<void> {
  if (bigramTable) return Promise.resolve();
  if (loadPromise) return loadPromise;

  loadPromise = fetch("/models/bigrams.json")
    .then((res) => {
      if (!res.ok) throw new Error(`bigrams.json: ${res.status}`);
      return res.json();
    })
    .then((data: BigramTable) => {
      bigramTable = data;
    })
    .catch((err) => {
      console.warn("[ngram] Failed to load bigrams.json:", err);
      bigramTable = {};
    });

  return loadPromise;
}

/** Check if bigrams are loaded */
export function isBigramReady(): boolean {
  return bigramTable !== null;
}

/**
 * Get top-3 suggestions from bigram table given the last typed word.
 */
export function getFallbackSuggestions(
  text: string
): [string, string, string] {
  if (!bigramTable) return DEFAULT_SUGGESTIONS;

  // Extract the last complete word (before trailing space) or current word
  const trimmed = text.trimEnd();
  const words = trimmed.split(/\s+/);
  const lastWord = (words[words.length - 1] || "").toLowerCase();

  if (!lastWord) return DEFAULT_SUGGESTIONS;

  const completions = bigramTable[lastWord];
  if (completions && completions.length > 0) {
    return [
      completions[0] || "",
      completions[1] || "",
      completions[2] || "",
    ] as [string, string, string];
  }

  return DEFAULT_SUGGESTIONS;
}
