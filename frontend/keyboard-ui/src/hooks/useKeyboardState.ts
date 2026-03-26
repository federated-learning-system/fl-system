import { useCallback, useReducer } from "react";

export type RoundState = "IDLE" | "OPEN" | "COLLECTING" | "DONE";

export interface KeyboardState {
  text: string;
  contextBuffer: number[];
  suggestions: [string, string, string];
  modelVersion: string;
  roundState: RoundState;
  dpEpsilon: number;
  dpBudget: number;
  trainingBuffer: number;
  shiftActive: boolean;
  numbersActive: boolean;
}

type Action =
  | { type: "TYPE_CHAR"; char: string }
  | { type: "BACKSPACE" }
  | { type: "ENTER" }
  | { type: "SPACE" }
  | { type: "TOGGLE_SHIFT" }
  | { type: "TOGGLE_NUMBERS" }
  | { type: "SELECT_SUGGESTION"; index: number }
  | { type: "SET_SUGGESTIONS"; suggestions: [string, string, string] }
  | { type: "SET_MODEL_VERSION"; version: string }
  | { type: "SET_ROUND_STATE"; state: RoundState }
  | { type: "SET_DP"; epsilon: number; budget: number }
  | { type: "INCREMENT_BUFFER" };

const CONTEXT_WINDOW = 10;

const initialState: KeyboardState = {
  text: "",
  contextBuffer: [],
  suggestions: ["", "", ""],
  modelVersion: "v0.0.0",
  roundState: "IDLE",
  dpEpsilon: 0.0,
  dpBudget: 1.0,
  trainingBuffer: 0,
  shiftActive: false,
  numbersActive: false,
};

function reducer(state: KeyboardState, action: Action): KeyboardState {
  switch (action.type) {
    case "TYPE_CHAR": {
      const char = state.shiftActive
        ? action.char.toUpperCase()
        : action.char;
      const newText = state.text + char;
      const newBuffer = [
        ...state.contextBuffer.slice(-(CONTEXT_WINDOW - 1)),
        char.charCodeAt(0),
      ];
      return {
        ...state,
        text: newText,
        contextBuffer: newBuffer,
        shiftActive: false,
      };
    }
    case "BACKSPACE": {
      if (state.text.length === 0) return state;
      return {
        ...state,
        text: state.text.slice(0, -1),
        contextBuffer: state.contextBuffer.slice(0, -1),
      };
    }
    case "ENTER":
      return {
        ...state,
        text: state.text + "\n",
        trainingBuffer: state.trainingBuffer + 1,
      };
    case "SPACE":
      return {
        ...state,
        text: state.text + " ",
        contextBuffer: [
          ...state.contextBuffer.slice(-(CONTEXT_WINDOW - 1)),
          32,
        ],
        trainingBuffer: state.trainingBuffer + 1,
      };
    case "TOGGLE_SHIFT":
      return { ...state, shiftActive: !state.shiftActive, numbersActive: false };
    case "TOGGLE_NUMBERS":
      return { ...state, numbersActive: !state.numbersActive, shiftActive: false };
    case "SELECT_SUGGESTION": {
      const word = state.suggestions[action.index];
      if (!word) return state;
      const parts = state.text.split(/(\s+)/);
      parts[parts.length - 1] = word;
      const newText = parts.join("") + " ";
      return { ...state, text: newText, trainingBuffer: state.trainingBuffer + 1 };
    }
    case "SET_SUGGESTIONS":
      return { ...state, suggestions: action.suggestions };
    case "SET_MODEL_VERSION":
      return { ...state, modelVersion: action.version };
    case "SET_ROUND_STATE":
      return { ...state, roundState: action.state };
    case "SET_DP":
      return { ...state, dpEpsilon: action.epsilon, dpBudget: action.budget };
    case "INCREMENT_BUFFER":
      return { ...state, trainingBuffer: state.trainingBuffer + 1 };
    default:
      return state;
  }
}

export function useKeyboardState() {
  const [state, dispatch] = useReducer(reducer, initialState);

  const typeChar = useCallback(
    (char: string) => dispatch({ type: "TYPE_CHAR", char }),
    []
  );
  const backspace = useCallback(() => dispatch({ type: "BACKSPACE" }), []);
  const enter = useCallback(() => dispatch({ type: "ENTER" }), []);
  const space = useCallback(() => dispatch({ type: "SPACE" }), []);
  const toggleShift = useCallback(() => dispatch({ type: "TOGGLE_SHIFT" }), []);
  const toggleNumbers = useCallback(
    () => dispatch({ type: "TOGGLE_NUMBERS" }),
    []
  );
  const selectSuggestion = useCallback(
    (index: number) => dispatch({ type: "SELECT_SUGGESTION", index }),
    []
  );
  const setSuggestions = useCallback(
    (suggestions: [string, string, string]) =>
      dispatch({ type: "SET_SUGGESTIONS", suggestions }),
    []
  );
  const setModelVersion = useCallback(
    (version: string) => dispatch({ type: "SET_MODEL_VERSION", version }),
    []
  );
  const setRoundState = useCallback(
    (roundState: RoundState) =>
      dispatch({ type: "SET_ROUND_STATE", state: roundState }),
    []
  );
  const setDP = useCallback(
    (epsilon: number, budget: number) =>
      dispatch({ type: "SET_DP", epsilon, budget }),
    []
  );

  return {
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
    setDP,
  };
}
