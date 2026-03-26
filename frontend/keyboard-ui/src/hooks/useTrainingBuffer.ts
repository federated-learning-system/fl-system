import { useCallback, useEffect, useRef, useState } from "react";
import { TrainingBuffer } from "../training/training_buffer";

export function useTrainingBuffer() {
  const [bufferSize, setBufferSize] = useState(0);
  const bufferRef = useRef<TrainingBuffer | null>(null);

  useEffect(() => {
    const buf = new TrainingBuffer((count) => setBufferSize(count));
    bufferRef.current = buf;
    setBufferSize(buf.size);
  }, []);

  const recordKeystroke = useCallback((tokenId: number) => {
    bufferRef.current?.push(tokenId, false);
  }, []);

  const recordSuggestionAccepted = useCallback((tokenId: number) => {
    bufferRef.current?.push(tokenId, true);
  }, []);

  return { bufferSize, recordKeystroke, recordSuggestionAccepted };
}
