import type { Line } from "@/lib/types";

// Same label in French and English.
const KIND: Record<Line["kind"], string> = { metro: "M", rer: "RER", tram: "T", transilien: "Train" };

/** Line badge in the line's official colour (open "référentiel des lignes" data). The outline
 *  takes the screen's ink so yellow holds on Signal and dark purples hold on Nuit. */
export function LineBadge({ line }: { line: Line }) {
  const shape = line.kind === "metro" ? "round" : line.kind === "tram" ? "pill" : "square";
  return (
    <span
      className={`badge badge-${shape}`}
      style={{ background: line.color ?? "#777", color: line.text_color ?? "#fff" }}
      title={`${KIND[line.kind]} ${line.name}`}
    >
      {line.name}
    </span>
  );
}

export function LineBadges({ lines, label }: { lines: Line[]; label: string }) {
  if (!lines.length) return null;
  return (
    <div className="badges" aria-label={label}>
      {lines.map((l) => (
        <LineBadge key={l.id} line={l} />
      ))}
    </div>
  );
}
