// People on the platform (design spec, section 6 "People"). Positions come from a seeded
// generator, so a station always shows the same crowd for a given state and screen size.
export interface Person {
  /** Centre x of the figure and y of the head centre, in SVG units. */
  x: number;
  y: number;
  /** 1 = head radius 8, body 22 × 60. */
  scale: number;
}

export interface CrowdRow {
  /** 0 = farthest … 5 = nearest. Picks the shading. */
  depth: number;
  blur: number;
  people: Person[];
}

/** Small deterministic generator (mulberry32). */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function seedOf(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Row geometry of the full platform, far to near, for a 400-unit-tall band (phone mockup). */
const FULL_ROWS = [
  { scale: 0.5, y: 40, blur: 6 },
  { scale: 0.6, y: 78, blur: 4.5 },
  { scale: 0.725, y: 122, blur: 3 },
  { scale: 0.86, y: 172, blur: 1.5 },
  { scale: 1.025, y: 231, blur: 0 },
  { scale: 1.225, y: 301, blur: 0 },
];

export interface FullCrowdOptions {
  width: number;
  /** Height of the band the rows are laid out in; 400 reproduces the phone mockup. */
  height?: number;
  /** "very_busy": six dense rows. "busy": the four nearest rows, wider gaps. */
  density: "busy" | "very_busy";
  seed: number;
  /** Multiplies every figure (tablet and computer draw larger people). */
  scale?: number;
}

/** Dense receding rows: far rows smaller, darker and more blurred. Regular spacing is fine here. */
export function fullCrowd({ width, height = 400, density, seed, scale = 1 }: FullCrowdOptions): CrowdRow[] {
  const rand = rng(seed);
  const k = height / 400;
  const rows = density === "very_busy" ? FULL_ROWS : FULL_ROWS.slice(2);
  const gap = density === "very_busy" ? 1.85 : 2.6;
  return rows.map((r) => {
    const s = r.scale * scale;
    const step = 22 * s * gap;
    const people: Person[] = [];
    for (let x = -step * rand(); x < width + step; x += step) {
      people.push({ x: x + (rand() - 0.5) * 6 * s, y: r.y * k + (rand() - 0.5) * 8 * s, scale: s });
    }
    return { depth: FULL_ROWS.indexOf(r), blur: r.blur, people };
  });
}

export interface Zone {
  x0: number;
  x1: number;
  /** y of the head centre. */
  y: number;
  scale: number;
  blur: number;
  depth: number;
  count: number;
  /** Put two of the figures shoulder to shoulder (the spec asks for one overlapping pair). */
  pair?: boolean;
  /** Horizontal spans to keep free (rabbit, chart labels…). */
  avoid?: [number, number][];
}

/** A few people placed irregularly in a zone: uneven gaps, never on a regular step. */
export function scatter(zone: Zone, seed: number): CrowdRow {
  const rand = rng(seed);
  const w = 22 * zone.scale;
  const free = (x: number) => !(zone.avoid ?? []).some(([a, b]) => x + w / 2 > a && x - w / 2 < b);
  const xs: number[] = [];
  let guard = 0;
  while (xs.length < zone.count && guard < 400) {
    guard += 1;
    const x = zone.x0 + rand() * (zone.x1 - zone.x0);
    if (!free(x)) continue;
    if (xs.some((o) => Math.abs(o - x) < w * 1.5)) continue;
    xs.push(x);
  }
  if (zone.pair && xs.length >= 2) {
    const i = Math.floor(rand() * xs.length);
    const x = xs[i] + w * 0.8;
    if (free(x)) xs[(i + 1) % xs.length] = x;
  }
  xs.sort((a, b) => a - b);
  return {
    depth: zone.depth,
    blur: zone.blur,
    people: xs.map((x) => ({ x, y: zone.y + (rand() - 0.5) * 10 * zone.scale, scale: zone.scale })),
  };
}
