/**
 * Training data capture buffer.
 *
 * Records keystroke events (token_id + accepted flag) into localStorage.
 * Auto-flushes to the client agent when buffer reaches FLUSH_THRESHOLD.
 */

export interface TrainingEvent {
  token_id: number;
  accepted: boolean;
  timestamp_ms: number;
}

const STORAGE_KEY = "fls_training_buffer";
const FLUSH_THRESHOLD = 50;
const POST_URL = "/api/client/training-buffer";

export class TrainingBuffer {
  private _buffer: TrainingEvent[] = [];
  private _flushing = false;
  private _onBufferChange: ((count: number) => void) | null = null;

  constructor(onChange?: (count: number) => void) {
    this._onBufferChange = onChange ?? null;
    this._loadFromStorage();
  }

  get size(): number {
    return this._buffer.length;
  }

  /** Record a keystroke event. */
  push(tokenId: number, accepted: boolean): void {
    this._buffer.push({
      token_id: tokenId,
      accepted,
      timestamp_ms: Date.now(),
    });
    this._saveToStorage();
    this._notify();

    if (this._buffer.length >= FLUSH_THRESHOLD) {
      this.flush();
    }
  }

  /** Flush buffer to the client agent endpoint. */
  async flush(): Promise<boolean> {
    if (this._buffer.length === 0 || this._flushing) return false;

    this._flushing = true;
    const events = [...this._buffer];

    try {
      const resp = await fetch(POST_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ events }),
      });

      if (resp.ok) {
        this._buffer = [];
        this._saveToStorage();
        this._notify();
        return true;
      }
      // Server error — keep buffer for retry
      console.warn(`Training buffer flush failed: ${resp.status}`);
      return false;
    } catch {
      // Network error — keep buffer for retry
      console.warn("Training buffer flush failed: network error");
      return false;
    } finally {
      this._flushing = false;
    }
  }

  /** Clear buffer without sending. */
  clear(): void {
    this._buffer = [];
    this._saveToStorage();
    this._notify();
  }

  private _loadFromStorage(): void {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        this._buffer = JSON.parse(raw);
        this._notify();
      }
    } catch {
      this._buffer = [];
    }
  }

  private _saveToStorage(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this._buffer));
    } catch {
      // Storage full — silently drop
    }
  }

  private _notify(): void {
    this._onBufferChange?.(this._buffer.length);
  }
}
