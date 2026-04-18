/**
 * Pure-JS BPE tokenizer compatible with SentencePiece vocab_8192.
 *
 * Strategy: greedy longest-match tokenization against the vocab.
 * This is a simplified BPE decoder that works with the frozen vocab
 * (no merge table needed — we greedily match the longest known piece).
 *
 * SentencePiece convention: words are prefixed with ▁ (U+2581).
 * Example: "hello world" → ["▁hello", "▁world"] → BPE subwords.
 */

const WHITESPACE_PREFIX = "\u2581"; // ▁

// Special token IDs
const PAD_ID = 0;
const UNK_ID = 1;
const BOS_ID = 2;
const EOS_ID = 3;

export class BPETokenizer {
  private tokenToId: Map<string, number> = new Map();
  private idToToken: Map<number, string> = new Map();
  private maxTokenLen = 0;
  private ready = false;

  /** Load vocab from a JSON URL (e.g., /models/vocab_8192.json). */
  async load(vocabUrl: string): Promise<void> {
    const resp = await fetch(vocabUrl);
    if (!resp.ok) throw new Error(`Failed to load vocab: ${resp.status}`);
    const vocab: Record<string, number> = await resp.json();

    this.tokenToId.clear();
    this.idToToken.clear();
    this.maxTokenLen = 0;

    for (const [token, id] of Object.entries(vocab)) {
      this.tokenToId.set(token, id);
      this.idToToken.set(id, token);
      if (token.length > this.maxTokenLen) {
        this.maxTokenLen = token.length;
      }
    }

    this.ready = true;
    console.log(`[bpe] Loaded vocab: ${this.tokenToId.size} tokens, max length ${this.maxTokenLen}`);
  }

  get isReady(): boolean {
    return this.ready;
  }

  get vocabSize(): number {
    return this.tokenToId.size;
  }

  /**
   * Encode text to token IDs.
   *
   * 1. Split on whitespace → words
   * 2. Prefix each word with ▁ (SentencePiece convention)
   * 3. Greedy longest-match tokenization against vocab
   * 4. Unknown characters → UNK_ID
   */
  encode(text: string): number[] {
    if (!this.ready) return [];
    const trimmed = text.trim();
    if (!trimmed) return [];

    const words = trimmed.split(/\s+/);
    const ids: number[] = [];

    for (const word of words) {
      // SentencePiece prefixes each word with ▁
      const prefixed = WHITESPACE_PREFIX + word.toLowerCase();
      this.tokenizeWord(prefixed, ids);
    }

    return ids;
  }

  /**
   * Greedy longest-match tokenization of a single prefixed word.
   * Tries progressively shorter substrings from each position.
   */
  private tokenizeWord(word: string, ids: number[]): void {
    let pos = 0;
    while (pos < word.length) {
      let matched = false;
      // Try longest possible match first
      const maxLen = Math.min(this.maxTokenLen, word.length - pos);
      for (let len = maxLen; len >= 1; len--) {
        const substr = word.slice(pos, pos + len);
        const id = this.tokenToId.get(substr);
        if (id !== undefined) {
          ids.push(id);
          pos += len;
          matched = true;
          break;
        }
      }
      if (!matched) {
        // Single character not in vocab → UNK
        ids.push(UNK_ID);
        pos++;
      }
    }
  }

  /** Decode token IDs back to text. */
  decode(ids: number[]): string {
    const pieces: string[] = [];
    for (const id of ids) {
      if (id === PAD_ID || id === BOS_ID || id === EOS_ID) continue;
      const piece = this.idToToken.get(id);
      if (piece) {
        pieces.push(piece);
      }
    }
    // Join pieces, convert ▁ back to space, trim leading space
    return pieces.join("").replace(/▁/g, " ").trim();
  }

  /** Decode a single token ID to its piece string. */
  decodeToken(id: number): string {
    return this.idToToken.get(id) ?? "[UNK]";
  }

  /** Look up a token's ID. Returns UNK_ID if not found. */
  tokenToIdLookup(token: string): number {
    return this.tokenToId.get(token) ?? UNK_ID;
  }
}
