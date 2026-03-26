import { useCallback, useEffect, useRef, useState } from "react";
import { OnnxInference } from "../inference/onnx_inference";
import { fetchServerSuggestions } from "../inference/server_inference";
import type { BPETokenizer } from "../tokenizer/bpe_tokenizer";

const MODEL_URL = "/models/model_quant.onnx";
const DEBOUNCE_MS = 30;

export function useInference(tokenizer: BPETokenizer | null) {
  const engineRef = useRef<OnnxInference | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [suggestions, setSuggestions] = useState<[string, string, string]>([
    "",
    "",
    "",
  ]);

  useEffect(() => {
    const engine = new OnnxInference();
    engineRef.current = engine;

    engine
      .load(MODEL_URL)
      .then(() => setLoading(false))
      .catch((err) => {
        console.warn("ONNX load failed, will use server fallback:", err);
        setError(err.message);
        setLoading(false);
      });
  }, []);

  const infer = useCallback(
    (text: string) => {
      if (timerRef.current) clearTimeout(timerRef.current);

      timerRef.current = setTimeout(async () => {
        if (!text.trim()) {
          setSuggestions(["", "", ""]);
          return;
        }

        try {
          let tokenIds: number[] = [];
          if (tokenizer?.loaded) {
            tokenIds = tokenizer.encode(text);
          }

          if (tokenIds.length === 0) {
            setSuggestions(["", "", ""]);
            return;
          }

          const engine = engineRef.current;
          if (engine?.loaded && tokenizer) {
            const results = await engine.getSuggestions(
              tokenIds,
              3,
              (id) => tokenizer.decodeToken(id),
            );
            setSuggestions([
              results[0] ?? "",
              results[1] ?? "",
              results[2] ?? "",
            ]);
          } else {
            // Server fallback
            try {
              const results = await fetchServerSuggestions(tokenIds, 3);
              setSuggestions([
                results[0] ?? "",
                results[1] ?? "",
                results[2] ?? "",
              ]);
            } catch {
              // Server not available — clear suggestions silently
              setSuggestions(["", "", ""]);
            }
          }
        } catch (err) {
          console.warn("Inference error:", err);
          setSuggestions(["", "", ""]);
        }
      }, DEBOUNCE_MS);
    },
    [tokenizer],
  );

  return { suggestions, infer, loading, error };
}
