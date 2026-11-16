import type { Line } from "@/lib/types";

/** Line badge in the line's official web colour (colours from referentiel-des-lignes). */
export function LineBadge({ line, size = "md" }: { line: Line; size?: "sm" | "md" }) {
  const shape = line.kind === "metro" ? "round" : line.kind === "tram" ? "pill" : "square";
  return (
    <span
      className={`badge badge-${shape} badge-${size}`}
      style={{ background: line.color ?? "#777", color: line.text_color ?? "#fff" }}
      title={`${line.kind === "metro" ? "M" : line.kind.toUpperCase()} ${line.name}`}
    >
      {line.name}
    </span>
  );
}

export function LineBadges({ lines, size }: { lines: Line[]; size?: "sm" | "md" }) {
  return (
    <span className="badges">
      {lines.map((l) => (
        <LineBadge key={l.id} line={l} size={size} />
      ))}
    </span>
  );
}
