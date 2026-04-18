import { useCallback, useEffect, useRef, useState } from "react";
import { FLSWebSocketClient } from "../ws/ws_client";
import type { RoundState } from "./useKeyboardState";
import type { OnnxInference } from "../inference/onnx_inference";

const WS_URL =
  (typeof window !== "undefined" &&
    `ws://${window.location.hostname}:8080/ws`) ||
  "ws://localhost:8080/ws";

interface UseWebSocketOptions {
  onRoundState: (state: RoundState) => void;
  onModelVersion: (version: string) => void;
  onToast: (message: string) => void;
  inferenceEngine: OnnxInference | null;
}

export function useWebSocket({
  onRoundState,
  onModelVersion,
  onToast,
  inferenceEngine,
}: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const clientRef = useRef<FLSWebSocketClient | null>(null);
  const engineRef = useRef(inferenceEngine);
  engineRef.current = inferenceEngine;

  const handleModelUpdated = useCallback(
    async (version: string, modelUrl: string) => {
      onModelVersion(version);

      // Hot-swap: download new model and replace session
      if (engineRef.current && modelUrl) {
        try {
          onToast(`Downloading model ${version}...`);
          await engineRef.current.load(modelUrl);
          engineRef.current.resetHidden();
          onToast(`Model updated to ${version}`);
        } catch (err) {
          console.warn("Model hot-swap failed:", err);
          onToast(`Model swap failed — using previous model`);
        }
      } else {
        onToast(`Model updated to ${version}`);
      }
    },
    [onModelVersion, onToast],
  );

  useEffect(() => {
    const client = new FLSWebSocketClient(WS_URL, {
      onRoundState,
      onModelUpdated: handleModelUpdated,
      onConnectionChange: setIsConnected,
    });

    clientRef.current = client;
    client.connect();

    return () => {
      client.disconnect();
    };
  }, [onRoundState, handleModelUpdated]);

  return { isConnected };
}
