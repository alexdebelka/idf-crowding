import type { CrowdRow } from "@/lib/crowd";

// Light-to-shadow shading per depth, far (0) to near (5): [light, mid, shadow].
const NIGHT: [string, string, string][] = [
  ["#565b62", "#1B212B", "#12151c"],
  ["#5c616a", "#232A36", "#171b23"],
  ["#636973", "#2C3442", "#1d222b"],
  ["#6d7583", "#3A4558", "#262d39"],
  ["#798291", "#4A566B", "#303846"],
  ["#838a97", "#586172", "#393f4a"],
];
// On Signal: far figures in olive, near figures in Nuit.
const CALM: [string, string, string][] = [
  ["#98a56c", "#6f7f33", "#4b571d"],
  ["#818c59", "#55641F", "#374114"],
  ["#818c59", "#55641F", "#374114"],
  ["#6b7347", "#2f3a17", "#1c230d"],
  ["#4d4f53", "#0E1116", "#090b0e"],
  ["#4d4f53", "#0E1116", "#090b0e"],
];

const r1 = (n: number) => Math.round(n * 10) / 10;

/** People as head circle + capsule body (head radius 8, body 22 × 60 at scale 1), diagonal
 *  light-to-shadow shading, far rows blurred. Decorative: the headline carries the state. */
export function People({
  rows,
  width,
  height,
  tone,
  id,
  className,
}: {
  rows: CrowdRow[];
  width: number;
  height: number;
  tone: "night" | "calm";
  /** Unique per SVG on the page (gradient ids). */
  id: string;
  className?: string;
}) {
  const shades = tone === "night" ? NIGHT : CALM;
  const depths = [...new Set(rows.map((r) => r.depth))];
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      className={className}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      preserveAspectRatio="xMidYMax slice"
    >
      <defs>
        {depths.map((d) => {
          const [a, b, c] = shades[Math.max(0, Math.min(5, d))];
          return (
            <linearGradient key={d} id={`${id}-d${d}`} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor={a} />
              <stop offset="0.5" stopColor={b} />
              <stop offset="1" stopColor={c} />
            </linearGradient>
          );
        })}
      </defs>
      {rows.map((row, i) => (
        <g key={i} style={row.blur ? { filter: `blur(${row.blur}px)` } : undefined}>
          {row.people.map((p, j) => {
            const w = 22 * p.scale;
            const h = 60 * p.scale;
            const r = 8 * p.scale;
            const fill = `url(#${id}-d${row.depth})`;
            return (
              <g key={j}>
                <circle cx={r1(p.x)} cy={r1(p.y)} r={r1(r)} fill={fill} />
                <rect x={r1(p.x - w / 2)} y={r1(p.y + r + 3 * p.scale)} width={r1(w)} height={r1(h)} rx={r1(w / 2)} fill={fill} />
              </g>
            );
          })}
        </g>
      ))}
    </svg>
  );
}
