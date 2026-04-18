import { useEffect, useRef, useCallback } from "react";
import { useKeyboardState } from "./hooks/useKeyboardState";
import { TextDisplay } from "./components/TextDisplay";
import { KeyboardLayout } from "./components/KeyboardLayout";
import { initPipeline, getSuggestions, initOnnx } from "./inference/inference_pipeline";
import { useWebSocket, type WSMessage } from "./hooks/useWebSocket";
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

  // ── Initialize inference pipeline on mount ──
  const initialized = useRef(false);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    initPipeline().then(() => {
      // Fetch initial suggestions
      getSuggestions("").then(({ suggestions, source }) => {
        setSuggestions(suggestions, source);
      });
    });
  }, [setSuggestions]);

  // ── Fetch suggestions when text changes (debounced) ──
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => {
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      getSuggestions(state.text).then(({ suggestions, source }) => {
        setSuggestions(suggestions, source);
      });
    }, 150);
    return () => clearTimeout(debounceRef.current);
  }, [state.text, setSuggestions]);

  // ── One-shot health check for initial model version ──
  useEffect(() => {
    fetch("/api/health", { signal: AbortSignal.timeout(3000) })
      .then((r) => r.json())
      .then((d) => { if (d.model_version) setModelVersion(d.model_version); })
      .catch(() => {});
  }, [setModelVersion]);

  // ── WebSocket: real-time round state + model hot-swap ──
  const handleWSMessage = useCallback(
    (msg: WSMessage) => {
      if (msg.event === "ROUND_OPENED" || msg.event === "ROUND_OPEN") {
        setRoundState("OPEN");
      } else if (msg.event === "ROUND_CLOSED" || msg.event === "ROUND_CLOSE") {
        setRoundState("COLLECTING");
      } else if (msg.event === "MODEL_UPDATED") {
        const version = (msg.payload?.version || msg.version) as string;
        if (version) setModelVersion(version);
        // Reload ONNX model with new weights, then refresh suggestions
        initOnnx().then(() => {
          getSuggestions(state.text).then(({ suggestions, source }) => {
            setSuggestions(suggestions, source);
          });
        });
      }
    },
    [setRoundState, setModelVersion, setSuggestions, state.text]
  );

  const wsUrl = `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws`;
  useWebSocket({ url: wsUrl, onMessage: handleWSMessage });

  // ── Start Round handler ──
  const handleStartRound = useCallback(() => {
    setRoundState("OPEN");
    fetch("/api/rounds/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.json();
      })
      .then(() => {
        // Round started — state will update via polling
        // Poll round status periodically
        const pollRound = setInterval(() => {
          fetch("/api/rounds/current", { signal: AbortSignal.timeout(3000) })
            .then((r) => r.json())
            .then((d) => {
              const s = d.state || d.round_state || "";
              if (s === "COLLECTING") setRoundState("COLLECTING");
              else if (s === "DONE") {
                setRoundState("DONE");
                clearInterval(pollRound);
                // Reset to IDLE after 5 seconds
                setTimeout(() => setRoundState("IDLE"), 5000);
              }
            })
            .catch(() => {});
        }, 3000);
        // Safety: stop polling after 10 minutes
        setTimeout(() => clearInterval(pollRound), 600_000);
      })
      .catch((err) => {
        console.error("[round] Start failed:", err);
        setRoundState("IDLE");
      });
  }, [setRoundState]);

  return (
    <div className="flex flex-col h-full max-w-md mx-auto relative">
      {/* header bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border-dim bg-surface">
        <span className="text-[11px] text-accent tracking-[0.15em] font-semibold font-[family-name:var(--font-display)]">
          FLS KEYBOARD
        </span>
        <span className="text-[10px] text-text-dim tracking-wider">
          FEDERATED LEARNING SYSTEM
        </span>
      </div>

      {/* text display area */}
      <TextDisplay text={state.text} />

      {/* keyboard */}
      <KeyboardLayout
        shiftActive={state.shiftActive}
        numbersActive={state.numbersActive}
        suggestions={state.suggestions}
        trainingBuffer={state.trainingBuffer}
        dpEpsilon={state.dpEpsilon}
        dpBudget={state.dpBudget}
        modelVersion={state.modelVersion}
        modelSource={state.modelSource}
        roundState={state.roundState}
        onTypeChar={typeChar}
        onBackspace={backspace}
        onEnter={enter}
        onSpace={space}
        onToggleShift={toggleShift}
        onToggleNumbers={toggleNumbers}
        onSelectSuggestion={selectSuggestion}
        onStartRound={handleStartRound}
      />
    </div>
  );
}

export default App;
