/**
 * @vitest-environment node
 */
import { describe, it, expect, beforeAll } from "vitest";
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { BPETokenizer, type VocabData } from "../tokenizer/bpe_tokenizer";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

describe("BPETokenizer", () => {
  let tokenizer: BPETokenizer;

  beforeAll(() => {
    const vocabPath = resolve(__dirname, "../../public/vocab/vocab_8192.json");
    const raw = readFileSync(vocabPath, "utf-8");
    const data: VocabData = JSON.parse(raw);

    tokenizer = new BPETokenizer();
    tokenizer.loadFromData(data);
  });

  it("vocab size is 8192", () => {
    expect(tokenizer.vocabSize()).toBe(8192);
  });

  it("encodes text to integer array", () => {
    const ids = tokenizer.encode("hello world");
    expect(ids.length).toBeGreaterThan(0);
    for (const id of ids) {
      expect(id).toBeGreaterThanOrEqual(0);
      expect(id).toBeLessThan(8192);
    }
  });

  it("decode single token returns string", () => {
    const ids = tokenizer.encode("the");
    const decoded = tokenizer.decodeToken(ids[0]);
    expect(typeof decoded).toBe("string");
    expect(decoded.length).toBeGreaterThan(0);
  });

  it("round-trips common words", () => {
    const text = "the quick brown fox";
    const ids = tokenizer.encode(text);
    const decoded = tokenizer.decode(ids);
    expect(decoded).toBe(text);
  });

  it("handles empty string", () => {
    expect(tokenizer.encode("")).toEqual([]);
    expect(tokenizer.decode([])).toBe("");
  });

  it("encodes single characters", () => {
    const ids = tokenizer.encode("a");
    expect(ids.length).toBeGreaterThan(0);
    expect(ids[0]).toBeGreaterThanOrEqual(0);
  });
});
