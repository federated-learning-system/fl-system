/**
 * WebSocket client for the FLS WebSocket Push Service.
 *
 * Handles:
 *   - Auto-reconnect with exponential backoff (max 5 retries)
 *   - ROUND_OPEN / ROUND_CLOSED / MODEL_UPDATED event dispatch
 *   - Model hot-swap: downloads new ONNX model and swaps into inference engine
 */

import type { RoundState } from "../hooks/useKeyboardState";

export interface WSEvent {
  event: string;
  payload?: Record<string, unknown>;
  // Direct format from fedavg-engine: { version, round_id }
  version?: string;
  round_id?: string;
}

export interface WSCallbacks {
  onRoundState: (state: RoundState) => void;
  onModelUpdated: (version: string, modelUrl: string) => void;
  onConnectionChange: (connected: boolean) => void;
}

const MAX_RETRIES = 5;
const BASE_DELAY_MS = 1000;

export class FLSWebSocketClient {
  private _ws: WebSocket | null = null;
  private _url: string;
  private _callbacks: WSCallbacks;
  private _retryCount = 0;
  private _retryTimer: ReturnType<typeof setTimeout> | null = null;
  private _stopped = false;

  constructor(url: string, callbacks: WSCallbacks) {
    this._url = url;
    this._callbacks = callbacks;
  }

  connect(): void {
    this._stopped = false;
    this._retryCount = 0;
    this._open();
  }

  disconnect(): void {
    this._stopped = true;
    if (this._retryTimer) {
      clearTimeout(this._retryTimer);
      this._retryTimer = null;
    }
    if (this._ws) {
      this._ws.close(1000, "client disconnect");
      this._ws = null;
    }
    this._callbacks.onConnectionChange(false);
  }

  get connected(): boolean {
    return this._ws?.readyState === WebSocket.OPEN;
  }

  private _open(): void {
    if (this._stopped) return;

    try {
      this._ws = new WebSocket(this._url);
    } catch {
      this._scheduleReconnect();
      return;
    }

    this._ws.onopen = () => {
      this._retryCount = 0;
      this._callbacks.onConnectionChange(true);
    };

    this._ws.onclose = () => {
      this._callbacks.onConnectionChange(false);
      this._scheduleReconnect();
    };

    this._ws.onerror = () => {
      // onclose will fire after onerror — reconnect handled there
    };

    this._ws.onmessage = (event) => {
      this._handleMessage(event.data as string);
    };
  }

  private _scheduleReconnect(): void {
    if (this._stopped) return;
    if (this._retryCount >= MAX_RETRIES) {
      this._callbacks.onConnectionChange(false);
      return;
    }

    const delay = BASE_DELAY_MS * Math.pow(2, this._retryCount);
    this._retryCount++;
    this._retryTimer = setTimeout(() => this._open(), delay);
  }

  private _handleMessage(raw: string): void {
    let data: WSEvent;
    try {
      data = JSON.parse(raw);
    } catch {
      return;
    }

    // Handle wrapped format: { event: "ROUND_OPEN", payload: {...} }
    if (data.event) {
      switch (data.event) {
        case "ROUND_OPEN":
        case "ROUND_OPENED":
          this._callbacks.onRoundState("OPEN");
          break;
        case "ROUND_COLLECTING":
          this._callbacks.onRoundState("COLLECTING");
          break;
        case "ROUND_CLOSED":
        case "ROUND_DONE":
          this._callbacks.onRoundState("DONE");
          break;
        case "MODEL_UPDATED": {
          const payload = data.payload ?? {};
          const version = (payload.version ?? "") as string;
          const modelUrl = (payload.model_url ?? "") as string;
          if (version) {
            this._callbacks.onModelUpdated(version, modelUrl);
          }
          break;
        }
      }
      return;
    }

    // Handle direct format from fedavg-engine: { version, round_id }
    if (data.version && data.round_id) {
      this._callbacks.onModelUpdated(data.version, "");
    }
  }
}
