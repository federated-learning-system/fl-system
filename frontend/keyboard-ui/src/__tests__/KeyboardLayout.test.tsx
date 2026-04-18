import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import App from "../App";

describe("Keyboard renders all QWERTY keys", () => {
  it("renders all 26 letter keys", () => {
    render(<App />);
    const letters = "qwertyuiopasdfghjklzxcvbnm".split("");
    for (const letter of letters) {
      expect(screen.getByTestId(`key-${letter}`)).toBeInTheDocument();
    }
  });

  it("renders space, backspace, enter, shift, and numbers keys", () => {
    render(<App />);
    expect(screen.getByTestId("space-key")).toBeInTheDocument();
    expect(screen.getByTestId("backspace-key")).toBeInTheDocument();
    expect(screen.getByTestId("enter-key")).toBeInTheDocument();
    expect(screen.getByTestId("shift-key")).toBeInTheDocument();
    expect(screen.getByTestId("numbers-key")).toBeInTheDocument();
  });

  it("renders suggestion bar (loading or pills)", () => {
    render(<App />);
    const bar = screen.getByTestId("suggestion-bar");
    // Initial state shows loading spinner or suggestion pills
    expect(bar).toBeInTheDocument();
    const hasLoading = bar.textContent?.includes("Loading model");
    const hasPills = screen.queryByTestId("suggestion-0") !== null;
    expect(hasLoading || hasPills).toBe(true);
  });
});

describe("Typing updates text display", () => {
  it("shows typed characters in the text display", () => {
    render(<App />);
    const display = screen.getByTestId("text-display");

    fireEvent.mouseDown(screen.getByTestId("key-h"));
    fireEvent.mouseDown(screen.getByTestId("key-e"));
    fireEvent.mouseDown(screen.getByTestId("key-l"));
    fireEvent.mouseDown(screen.getByTestId("key-l"));
    fireEvent.mouseDown(screen.getByTestId("key-o"));

    expect(display).toHaveTextContent("hello");
  });
});

describe("Backspace removes last character", () => {
  it("removes the last typed character", () => {
    render(<App />);
    const display = screen.getByTestId("text-display");

    fireEvent.mouseDown(screen.getByTestId("key-h"));
    fireEvent.mouseDown(screen.getByTestId("key-i"));
    expect(display).toHaveTextContent("hi");

    fireEvent.mouseDown(screen.getByTestId("backspace-key"));
    expect(display).toHaveTextContent("h");
    expect(display).not.toHaveTextContent("hi");
  });

  it("does nothing when text is empty", () => {
    render(<App />);
    const display = screen.getByTestId("text-display");

    fireEvent.mouseDown(screen.getByTestId("backspace-key"));
    expect(display).toHaveTextContent("Start typing...");
  });
});

describe("Status bar renders with placeholder values", () => {
  it("shows training buffer count", () => {
    render(<App />);
    const status = screen.getByTestId("status-bar");
    expect(status).toHaveTextContent("0");
    expect(status).toHaveTextContent("samples");
  });

  it("shows DP epsilon", () => {
    render(<App />);
    const status = screen.getByTestId("status-bar");
    expect(status).toHaveTextContent("0.00/1.00");
  });

  it("shows model version", () => {
    render(<App />);
    const status = screen.getByTestId("status-bar");
    expect(status).toHaveTextContent("v0.0.0");
  });

  it("shows round state indicator", () => {
    render(<App />);
    const status = screen.getByTestId("status-bar");
    expect(status).toHaveTextContent("IDLE");
  });
});

describe("Shift toggle", () => {
  it("shows uppercase letters when shift is active", () => {
    render(<App />);

    fireEvent.mouseDown(screen.getByTestId("shift-key"));
    expect(screen.getByTestId("key-q")).toHaveTextContent("Q");

    // typing a key deactivates shift
    fireEvent.mouseDown(screen.getByTestId("key-a"));
    expect(screen.getByTestId("key-q")).toHaveTextContent("q");
  });
});

describe("Number toggle", () => {
  it("shows number row when toggled", () => {
    render(<App />);

    fireEvent.mouseDown(screen.getByTestId("numbers-key"));
    expect(screen.getByTestId("key-1")).toBeInTheDocument();
    expect(screen.getByTestId("key-0")).toBeInTheDocument();

    // toggle back
    fireEvent.mouseDown(screen.getByTestId("numbers-key"));
    expect(screen.getByTestId("key-q")).toBeInTheDocument();
  });
});

describe("Space increments training buffer", () => {
  it("increases sample count on space press", () => {
    render(<App />);
    const status = screen.getByTestId("status-bar");

    fireEvent.mouseDown(screen.getByTestId("key-h"));
    fireEvent.mouseDown(screen.getByTestId("key-i"));
    fireEvent.mouseDown(screen.getByTestId("space-key"));

    expect(status).toHaveTextContent("1 samples");
  });
});
