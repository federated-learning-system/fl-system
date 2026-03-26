/**
 * Browser-side BPE tokenizer compatible with the FLS SentencePiece model.
 *
 * Uses a greedy longest-match tokenization strategy against the trained
 * vocabulary (with scores for tie-breaking). This is not a full SentencePiece
 * unigram implementation but produces compatible output for the FLS LSTM model.
 *
 * The SentencePiece `▁` prefix convention is used: a leading `▁` on a piece
 * means "preceded by a space" (word boundary).
 */

export interface VocabData {
  vocab: Record<string, number>;
  scores: number[];
  reverse: string[];
  vocab_size: number;
}

const SP_SPACE = "\u2581"; // SentencePiece word-boundary marker ▁

// Special token IDs
const PAD_ID = 0;
const UNK_ID = 1;

export class BPETokenizer {
  private _vocab: Map<string, number> = new Map();
  private _reverse: string[] = [];
  private _scores: number[] = [];
  private _vocabSize = 0;
  private _loaded = false;

  /** Load vocabulary from a URL (fetches JSON). */
  async load(url: string): Promise<void> {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`Failed to load vocab: ${resp.status}`);
    const data: VocabData = await resp.json();
    this._initFromData(data);
  }

  /** Load vocabulary from an already-parsed object. */
  loadFromData(data: VocabData): void {
    this._initFromData(data);
  }

  private _initFromData(data: VocabData): void {
    this._vocab = new Map(Object.entries(data.vocab));
    this._reverse = data.reverse;
    this._scores = data.scores;
    this._vocabSize = data.vocab_size;
    this._loaded = true;
  }

  get loaded(): boolean {
    return this._loaded;
  }

  vocabSize(): number {
    return this._vocabSize;
  }

  /**
   * Encode text to token IDs using greedy longest-match with SentencePiece
   * word-boundary conventions.
   */
  encode(text: string): number[] {
    if (!this._loaded) throw new Error("Tokenizer not loaded");
    if (text.length === 0) return [];

    // Normalize: prepend ▁ and replace spaces with ▁
    const normalized = SP_SPACE + text.replace(/ /g, SP_SPACE);

    const ids: number[] = [];
    let i = 0;

    while (i < normalized.length) {
      let bestLen = 0;
      let bestId = UNK_ID;
      let bestScore = -Infinity;

      // Try all lengths from maxPieceLen down to 1
      const maxLen = Math.min(normalized.length - i, 48); // SentencePiece max piece ~48 chars
      for (let len = maxLen; len >= 1; len--) {
        const candidate = normalized.slice(i, i + len);
        const id = this._vocab.get(candidate);
        if (id !== undefined && id !== PAD_ID) {
          const score = this._scores[id];
          // Prefer longer matches; among same length prefer higher score
          if (len > bestLen || (len === bestLen && score > bestScore)) {
            bestLen = len;
            bestId = id;
            bestScore = score;
          }
        }
      }

      if (bestLen === 0) {
        // Unknown character — emit UNK and advance 1 char
        ids.push(UNK_ID);
        i += 1;
      } else {
        ids.push(bestId);
        i += bestLen;
      }
    }

    return ids;
  }

  /** Decode a sequence of token IDs back to text. */
  decode(ids: number[]): string {
    if (!this._loaded) throw new Error("Tokenizer not loaded");
    return ids
      .map((id) => this._reverse[id] ?? "")
      .join("")
      .replace(new RegExp(SP_SPACE, "g"), " ")
      .trimStart();
  }

  /** Decode a single token ID to its display string. */
  decodeToken(id: number): string {
    if (!this._loaded) throw new Error("Tokenizer not loaded");
    const piece = this._reverse[id] ?? "";
    return piece.replace(new RegExp(SP_SPACE, "g"), " ").trimStart();
  }
}
