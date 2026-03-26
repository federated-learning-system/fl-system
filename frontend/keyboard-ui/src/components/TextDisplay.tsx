interface TextDisplayProps {
  text: string;
}

export function TextDisplay({ text }: TextDisplayProps) {
  const lines = text.split("\n");
  const lastLine = lines[lines.length - 1] ?? "";

  return (
    <div
      data-testid="text-display"
      className="flex-1 flex flex-col justify-end px-5 pb-4 min-h-0"
    >
      {/* faint grid background */}
      <div className="absolute inset-0 pointer-events-none opacity-[0.03]"
        style={{
          backgroundImage:
            "linear-gradient(var(--color-accent) 1px, transparent 1px), linear-gradient(90deg, var(--color-accent) 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />

      <div className="relative overflow-y-auto max-h-full">
        {text.length === 0 ? (
          <p className="text-text-dim text-sm italic select-none">
            Start typing...
          </p>
        ) : (
          <div className="text-left">
            {lines.slice(0, -1).map((line, i) => (
              <p key={i} className="text-text-secondary text-base leading-relaxed break-words font-[family-name:var(--font-display)]">
                {line || "\u00A0"}
              </p>
            ))}
            <p className="text-text-primary text-lg leading-relaxed break-words font-[family-name:var(--font-display)]">
              {lastLine}
              <span className="inline-block w-[2px] h-[1.1em] bg-accent align-text-bottom ml-px animate-pulse" />
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
