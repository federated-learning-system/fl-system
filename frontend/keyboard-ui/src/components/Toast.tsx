import { useEffect, useState } from "react";

interface ToastProps {
  message: string;
  duration?: number;
  onDone: () => void;
}

export function Toast({ message, duration = 3000, onDone }: ToastProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Trigger enter animation
    requestAnimationFrame(() => setVisible(true));
    const timer = setTimeout(() => {
      setVisible(false);
      setTimeout(onDone, 300); // wait for exit animation
    }, duration);
    return () => clearTimeout(timer);
  }, [duration, onDone]);

  return (
    <div
      data-testid="toast"
      className={`
        fixed top-4 left-1/2 -translate-x-1/2 z-50
        px-4 py-2 rounded-lg
        bg-surface-raised border border-accent/30
        text-accent text-xs tracking-wide
        shadow-[0_0_20px_rgba(58,255,180,0.1)]
        transition-all duration-300 ease-out
        ${visible ? "opacity-100 translate-y-0" : "opacity-0 -translate-y-2"}
      `}
    >
      <span className="inline-block w-1.5 h-1.5 rounded-full bg-accent mr-2 glow-pulse" />
      {message}
    </div>
  );
}
