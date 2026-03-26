import { useEffect, useRef, useState } from "react";
import { BPETokenizer } from "../tokenizer/bpe_tokenizer";

const VOCAB_URL = "/vocab/vocab_8192.json";

export function useTokenizer() {
  const tokenizerRef = useRef<BPETokenizer | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const tok = new BPETokenizer();
    tokenizerRef.current = tok;

    tok
      .load(VOCAB_URL)
      .then(() => setLoading(false))
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  return { tokenizer: tokenizerRef.current, loading, error };
}
