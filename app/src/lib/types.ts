// Mirrors schemas/place.v1.schema.json and schemas/index.v1.schema.json (schema_version 1).
export const DAY_TYPES = ["JOHV", "JOVS", "SAHV", "SAVS", "DIJFP"] as const;
export type DayTypeCode = (typeof DAY_TYPES)[number];
export type Band = "quiet" | "moderate" | "busy" | "very_busy";
export const BANDS: Band[] = ["quiet", "moderate", "busy", "very_busy"];

export interface Line {
  id: string;
  name: string;
  kind: "metro" | "rer" | "transilien" | "tram";
  color?: string;
  text_color?: string;
}

export interface Period {
  start: string;
  end: string;
}

export interface Attribution {
  source: string;
  source_url: string;
  license: string;
  license_url: string;
}

export interface HourRow {
  h: number;
  expected_entries: number;
  score: number;
  band: Band;
}

export interface DayType {
  hours: HourRow[];
  daily_entries: number;
  n_days: number;
  low_confidence: boolean;
  best_slots: { quietest: number[]; around_peaks: { peak: number; alternative: number }[] };
}

export interface PlaceFile {
  schema_version: 1;
  generated_at: string;
  data_period: Period;
  profile_periods?: string[];
  place: {
    id: string;
    name: string;
    town?: string | null;
    lat?: number | null;
    lon?: number | null;
    station_ids: number[];
    lines: Line[];
  };
  reference_level: number;
  day_types: Partial<Record<DayTypeCode, DayType>>;
  attribution: Attribution;
}

export interface IndexPlace {
  id: string;
  name: string;
  town?: string | null;
  lat?: number | null;
  lon?: number | null;
  weekday_entries?: number | null;
  lines: Line[];
}

export interface IndexFile {
  schema_version: 1;
  generated_at: string;
  data_period: Period;
  bands?: { band: Band; below: number | null }[];
  places: IndexPlace[];
  attribution: Attribution;
}
