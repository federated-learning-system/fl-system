/**
 * ONNX Runtime Web inference engine for the FLS LSTM model.
 *
 * Model inputs:
 *   token_ids  [batch=1, seq_len=10] — int64
 *   hidden_h   [num_layers=2, batch=1, hidden=256] — float32
 *   hidden_c   [num_layers=2, batch=1, hidden=256] — float32
 *
 * Model outputs:
 *   logits         [batch=1, vocab_size=8192] — float32
 *   out_hidden_h   [2, 1, 256] — float32
 *   out_hidden_c   [2, 1, 256] — float32
 */

import * as ort from "onnxruntime-web";

const SEQ_LEN = 10;
const NUM_LAYERS = 2;
const HIDDEN_SIZE = 256;
const PAD_ID = 0;

export class OnnxInference {
  private _session: ort.InferenceSession | null = null;
  private _loaded = false;

  // Carry hidden state across inferences for autoregressive generation
  private _hiddenH: Float32Array;
  private _hiddenC: Float32Array;

  constructor() {
    const size = NUM_LAYERS * 1 * HIDDEN_SIZE;
    this._hiddenH = new Float32Array(size);
    this._hiddenC = new Float32Array(size);
  }

  get loaded(): boolean {
    return this._loaded;
  }

  /** Load the ONNX model from a URL. */
  async load(url: string): Promise<void> {
    // Use WASM backend (CPU) — works in all browsers
    ort.env.wasm.numThreads = 1;
    this._session = await ort.InferenceSession.create(url, {
      executionProviders: ["wasm"],
      graphOptimizationLevel: "all",
    });
    this._loaded = true;
  }

  /** Reset hidden state (e.g., on new conversation). */
  resetHidden(): void {
    this._hiddenH.fill(0);
    this._hiddenC.fill(0);
  }

  /**
   * Get top-K next-word suggestions given a context of token IDs.
   * Returns decoded token strings (caller must provide a decode function).
   */
  async getSuggestions(
    tokenIds: number[],
    topK: number = 3,
    decodeToken?: (id: number) => string,
  ): Promise<string[]> {
    if (!this._session) throw new Error("ONNX session not loaded");

    // Pad or truncate to SEQ_LEN
    const padded = new BigInt64Array(SEQ_LEN);
    const start = Math.max(0, tokenIds.length - SEQ_LEN);
    const contextIds = tokenIds.slice(start);

    // Left-pad with PAD_ID
    const offset = SEQ_LEN - contextIds.length;
    for (let i = 0; i < SEQ_LEN; i++) {
      padded[i] = i < offset
        ? BigInt(PAD_ID)
        : BigInt(contextIds[i - offset]);
    }

    const inputTensor = new ort.Tensor("int64", padded, [1, SEQ_LEN]);
    const hiddenHTensor = new ort.Tensor(
      "float32",
      new Float32Array(this._hiddenH),
      [NUM_LAYERS, 1, HIDDEN_SIZE],
    );
    const hiddenCTensor = new ort.Tensor(
      "float32",
      new Float32Array(this._hiddenC),
      [NUM_LAYERS, 1, HIDDEN_SIZE],
    );

    const results = await this._session.run({
      token_ids: inputTensor,
      hidden_h: hiddenHTensor,
      hidden_c: hiddenCTensor,
    });

    // Update hidden state
    const outH = results["out_hidden_h"];
    const outC = results["out_hidden_c"];
    if (outH?.data) this._hiddenH.set(outH.data as Float32Array);
    if (outC?.data) this._hiddenC.set(outC.data as Float32Array);

    // Extract logits and find top-K
    const logits = results["logits"].data as Float32Array;
    return this._topK(logits, topK, decodeToken);
  }

  private _topK(
    logits: Float32Array,
    k: number,
    decodeToken?: (id: number) => string,
  ): string[] {
    // Build array of [index, value] and partial sort for top-K
    const indexed: [number, number][] = [];
    for (let i = 5; i < logits.length; i++) {
      // Skip special tokens (0-4: PAD, UNK, BOS, EOS, SPACE)
      indexed.push([i, logits[i]]);
    }

    // Partial sort: just find top K
    indexed.sort((a, b) => b[1] - a[1]);
    const topIds = indexed.slice(0, k).map((pair) => pair[0]);

    if (decodeToken) {
      return topIds.map((id) => decodeToken(id));
    }
    return topIds.map((id) => String(id));
  }
}
