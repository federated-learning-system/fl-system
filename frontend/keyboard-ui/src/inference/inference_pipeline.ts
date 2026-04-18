/**
 * inference/inference_pipeline.ts
 *
 * Three-tier inference fallback chain:
 *   1. ONNX Runtime Web (local WASM) — fastest, works offline
 *   2. Server API (POST /api/infer)  — reliable, always has latest model
 *   3. N-gram bigram fallback        — instant, no network needed
 *
 * Returns top-3 next-word suggestions and reports which source was used.
 */

import * as ort from 'onnxruntime-web';
import {
  loadBigrams,
  isBigramReady,
  getFallbackSuggestions,
} from "./ngram_fallback";
import { BPETokenizer } from './bpe_tokenizer';

export type InferenceSource = "onnx" | "server" | "ngram" | "loading";

export interface InferenceResult {
  suggestions: [string, string, string];
  source: InferenceSource;
}

// ── ONNX state ──────────────────────────────────────────────────────────────

let onnxReady = false;
let onnxSession: ort.InferenceSession | null = null;

const SEQ_LEN = 10;
const PAD_ID = 0;
const NUM_LAYERS = 2;
const HIDDEN_SIZE = 256;

export async function initOnnx(): Promise<boolean> {
  try {
    onnxSession = await ort.InferenceSession.create('/models/model_quant.onnx', {
      executionProviders: ['wasm'],
    });
    onnxReady = true;
    console.log('[onnx] Model loaded successfully (WASM backend)');
    return true;
  } catch (err) {
    console.warn('[onnx] Failed to load model:', err);
    onnxReady = false;
    return false;
  }
}

async function inferFromOnnx(
  tokenIds: number[],
  tokenizer: BPETokenizer
): Promise<[string, string, string] | null> {
  if (!onnxSession) return null;
  try {
    // Pad/truncate to SEQ_LEN
    const padded = tokenIds.length >= SEQ_LEN
      ? tokenIds.slice(-SEQ_LEN)
      : Array(SEQ_LEN - tokenIds.length).fill(PAD_ID).concat(tokenIds);

    const inputIds = new ort.Tensor('int64', BigInt64Array.from(padded.map(BigInt)), [1, SEQ_LEN]);
    const hiddenH = new ort.Tensor('float32', new Float32Array(NUM_LAYERS * HIDDEN_SIZE), [NUM_LAYERS, 1, HIDDEN_SIZE]);
    const hiddenC = new ort.Tensor('float32', new Float32Array(NUM_LAYERS * HIDDEN_SIZE), [NUM_LAYERS, 1, HIDDEN_SIZE]);

    const results = await onnxSession.run({
      token_ids: inputIds,
      hidden_h: hiddenH,
      hidden_c: hiddenC,
    });

    const logits = results['logits'].data as Float32Array;
    // Top-3 from vocab_size=8192 logits
    const indexed = Array.from(logits).map((v, i) => ({ v, i }));
    indexed.sort((a, b) => b.v - a.v);
    const top3Ids = indexed.slice(0, 3).map((x) => x.i);

    // Decode token IDs to words using the BPE tokenizer
    const suggestions = top3Ids.map((id) => tokenizer.decode([id]).replace(/▁/g, ''));
    return [
      suggestions[0] || '',
      suggestions[1] || '',
      suggestions[2] || '',
    ] as [string, string, string];
  } catch {
    return null;
  }
}

// ── BPE tokenizer state ─────────────────────────────────────────────────────

let bpeTokenizer: BPETokenizer | null = null;

// ── Server inference ────────────────────────────────────────────────────────

const SERVER_TIMEOUT_MS = 3000;

async function inferFromServer(
  text: string
): Promise<[string, string, string] | null> {
  try {
    const words = text.trim().split(/\s+/).filter(Boolean);
    const lastTokens = words.slice(-5);

    // Use BPE token IDs if available; fall back to char-code heuristic
    let tokenIds: number[];
    if (bpeTokenizer && bpeTokenizer.isReady) {
      tokenIds = bpeTokenizer.encode(lastTokens.join(' '));
    } else {
      tokenIds = lastTokens.map((w) =>
        w.split("").reduce((acc, c) => acc + c.charCodeAt(0), 0) % 8192
      );
    }

    if (tokenIds.length === 0) return null;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), SERVER_TIMEOUT_MS);

    const resp = await fetch("/api/infer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token_ids: tokenIds, top_k: 3 }),
      signal: controller.signal,
    });

    clearTimeout(timeout);

    if (!resp.ok) return null;

    const data = await resp.json();
    const suggestions = data.suggestions as string[];
    if (!suggestions || suggestions.length === 0) return null;

    return [
      suggestions[0] || "",
      suggestions[1] || "",
      suggestions[2] || "",
    ] as [string, string, string];
  } catch {
    return null;
  }
}

// ── Pipeline ────────────────────────────────────────────────────────────────

let initialized = false;

/**
 * Initialize the inference pipeline.
 * Loads bigrams + BPE tokenizer immediately, attempts ONNX in background.
 */
export async function initPipeline(): Promise<void> {
  if (initialized) return;
  initialized = true;

  // Load BPE tokenizer (needed for both ONNX and server inference)
  bpeTokenizer = new BPETokenizer();
  bpeTokenizer.load('/models/vocab_8192.json').catch((err) => {
    console.warn('[bpe] Failed to load vocab:', err);
    bpeTokenizer = null;
  });

  // Load bigrams (fast, ~7KB)
  await loadBigrams();

  // Attempt ONNX init in background (don't block)
  initOnnx().catch(() => {});
}

/**
 * Get next-word suggestions using the fallback chain.
 * ONNX → Server API → N-gram bigrams
 */
export async function getSuggestions(
  text: string
): Promise<InferenceResult> {
  // If nothing typed, return defaults via ngram
  if (!text.trim()) {
    return {
      suggestions: getFallbackSuggestions(""),
      source: isBigramReady() ? "ngram" : "loading",
    };
  }

  // Tier 1: ONNX (local WASM — mirrors GBoard on-device inference)
  if (onnxReady && bpeTokenizer && bpeTokenizer.isReady) {
    const tokenIds = bpeTokenizer.encode(text);
    if (tokenIds.length > 0) {
      const onnxResult = await inferFromOnnx(tokenIds, bpeTokenizer);
      if (onnxResult) {
        return { suggestions: onnxResult, source: "onnx" };
      }
    }
  }

  // Tier 2: Server API
  const serverResult = await inferFromServer(text);
  if (serverResult) {
    return { suggestions: serverResult, source: "server" };
  }

  // Tier 3: N-gram fallback
  if (isBigramReady()) {
    return {
      suggestions: getFallbackSuggestions(text),
      source: "ngram",
    };
  }

  // Nothing ready yet
  return {
    suggestions: ["", "", ""],
    source: "loading",
  };
}
