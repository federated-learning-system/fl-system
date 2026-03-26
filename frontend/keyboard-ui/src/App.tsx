import { useKeyboardState } from "./hooks/useKeyboardState";
import { TextDisplay } from "./components/TextDisplay";
import { KeyboardLayout } from "./components/KeyboardLayout";
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
  } = useKeyboardState();

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
        roundState={state.roundState}
        onTypeChar={typeChar}
        onBackspace={backspace}
        onEnter={enter}
        onSpace={space}
        onToggleShift={toggleShift}
        onToggleNumbers={toggleNumbers}
        onSelectSuggestion={selectSuggestion}
      />
    </div>
  );
}

export default App;
