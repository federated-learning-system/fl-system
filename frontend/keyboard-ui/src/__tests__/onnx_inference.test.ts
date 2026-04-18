/**
 * @vitest-environment node
 */
import { describe, it, expect, beforeAll } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { OnnxInference } from "../inference/onnx_inference";
import { BPETokenizer, type VocabData } from "../tokenizer/bpe_tokenizer";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

describe("OnnxInference", () => {
  let engine: OnnxInference;
  let tokenizer: BPETokenizer;

  beforeAll(async () => {
    // Load tokenizer
    const vocabPath = resolve(__dirname, "../../public/vocab/vocab_8192.json");
    const vocabData: VocabData = JSON.parse(readFileSync(vocabPath, "utf-8"));
    tokenizer = new BPETokenizer();
    tokenizer.loadFromData(vocabData);

    // Load ONNX model from file buffer
    const modelPath = resolve(
      __dirname,
      "../../public/models/model_quant.onnx",
    );
    const modelBuffer = readFileSync(modelPath);

    engine = new OnnxInference();
    const ort = await import("onnxruntime-web");
    ort.env.wasm.numThreads = 1;

    const session = await ort.InferenceSession.create(
      modelBuffer.buffer as ArrayBuffer,
      { executionProviders: ["cpu"] },
    );
    // Inject the session directly
    Object.assign(engine, { _session: session, _loaded: true });
  }, 30000);

  it("returns 3 suggestions for a token sequence", async () => {
    const ids = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000];
    const suggestions = await engine.getSuggestions(ids, 3, (id) =>
      tokenizer.decodeToken(id),
    );
    expect(suggestions.length).toBe(3);
    for (const s of suggestions) {
      expect(typeof s).toBe("string");
    }
  });

  it("handles short context (padding)", async () => {
    const ids = [42, 100];
    const suggestions = await engine.getSuggestions(ids, 3, (id) =>
      tokenizer.decodeToken(id),
    );
    expect(suggestions.length).toBe(3);
  });

  it("inference completes within 100ms", async () => {
    const ids = Array(10).fill(42);
    // Warm-up
    await engine.getSuggestions(ids, 3);

    const t0 = performance.now();
    await engine.getSuggestions(ids, 3);
    const elapsed = performance.now() - t0;
    console.log(`Inference latency: ${elapsed.toFixed(1)}ms`);
    expect(elapsed).toBeLessThan(100);
  });
});
