import { useCallback, useEffect, useRef, useState } from "react";
import { useKeyboardState } from "./hooks/useKeyboardState";
import { useTokenizer } from "./hooks/useTokenizer";
import { useInference } from "./hooks/useInference";
import { useWebSocket } from "./hooks/useWebSocket";
import { useTrainingBuffer } from "./hooks/useTrainingBuffer";
import { TextDisplay } from "./components/TextDisplay";
import { KeyboardLayout } from "./components/KeyboardLayout";
import { Toast } from "./components/Toast";
import type { OnnxInference } from "./inference/onnx_inference";
import "./index.css";

function App() {
  const {
    state,
    typeChar,
    backspace,
    enter,
    space,
    toggleShift,
    toggleNumbers,
    selectSuggestion,
    setSuggestions,
    setModelVersion,
    setRoundState,
  } = useKeyboardState();

  // Tokenizer
  const { tokenizer } = useTokenizer();

  // Inference (ONNX)
  const { suggestions, infer } = useInference(tokenizer);

  // Keep a stable ref to the inference engine for WebSocket hot-swap
  const engineRef = useRef<OnnxInference | null>(null);
  useEffect(() => {
    // The useInference hook creates the engine internally;
    // we expose it through a ref for the WebSocket hook.
    // Since the engine is internal to useInference, we pass null
    // and let the WebSocket handle model URL download independently.
  }, []);

  // Toast state
  const [toast, setToast] = useState<string | null>(null);
  const showToast = useCallback((msg: string) => setToast(msg), []);

  // WebSocket
  const { isConnected } = useWebSocket({
    onRoundState: setRoundState,
    onModelVersion: setModelVersion,
    onToast: showToast,
    inferenceEngine: engineRef.current,
  });

  // Training buffer
  const { bufferSize, recordKeystroke, recordSuggestionAccepted } =
    useTrainingBuffer();

  // Update suggestions when text changes
  useEffect(() => {
    infer(state.text);
  }, [state.text, infer]);

  // Sync inference suggestions into keyboard state
  useEffect(() => {
    setSuggestions(suggestions);
  }, [suggestions, setSuggestions]);

  // Wrapped handlers that also record training events
  const handleTypeChar = useCallback(
    (char: string) => {
      typeChar(char);
      recordKeystroke(char.charCodeAt(0));
    },
    [typeChar, recordKeystroke],
  );

  const handleSpace = useCallback(() => {
    space();
    recordKeystroke(32);
  }, [space, recordKeystroke]);

  const handleEnter = useCallback(() => {
    enter();
    recordKeystroke(10);
  }, [enter, recordKeystroke]);

  const handleSelectSuggestion = useCallback(
    (index: number) => {
      const word = state.suggestions[index];
      selectSuggestion(index);
      if (word) {
        recordSuggestionAccepted(index);
      }
    },
    [selectSuggestion, state.suggestions, recordSuggestionAccepted],
  );

  return (
    <div className="flex flex-col h-full max-w-md mx-auto relative">
      {/* toast */}
      {toast && <Toast message={toast} onDone={() => setToast(null)} />}

      {/* header bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border-dim bg-surface">
        <span className="text-[11px] text-accent tracking-[0.15em] font-semibold font-[family-name:var(--font-display)]">
          FLS KEYBOARD
        </span>
        <div className="flex items-center gap-2">
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${isConnected ? "bg-accent" : "bg-red-500"}`}
            title={isConnected ? "WebSocket connected" : "Disconnected"}
          />
          <span className="text-[10px] text-text-dim tracking-wider">
            FEDERATED LEARNING SYSTEM
          </span>
        </div>
      </div>

      {/* text display area */}
      <TextDisplay text={state.text} />

      {/* keyboard */}
      <KeyboardLayout
        shiftActive={state.shiftActive}
        numbersActive={state.numbersActive}
        suggestions={state.suggestions}
        trainingBuffer={bufferSize}
        dpEpsilon={state.dpEpsilon}
        dpBudget={state.dpBudget}
        modelVersion={state.modelVersion}
        roundState={state.roundState}
        onTypeChar={handleTypeChar}
        onBackspace={backspace}
        onEnter={handleEnter}
        onSpace={handleSpace}
        onToggleShift={toggleShift}
        onToggleNumbers={toggleNumbers}
        onSelectSuggestion={handleSelectSuggestion}
      />
    </div>
  );
}

export default App;
