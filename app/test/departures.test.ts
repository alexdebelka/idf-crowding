// Next departures: reading the PRIM stop-monitoring answer (SIRI Lite) and counting minutes.
import { describe, expect, it } from "vitest";
import { isAnswer, lineIdOf, minutesUntil, parseStopMonitoring, stillAhead } from "@/lib/departures";

const NOW = Date.parse("2026-11-19T12:00:00Z");
const at = (min: number) => new Date(NOW + min * 60_000).toISOString();

function visit(line: string, dest: string, min: number, extra: Record<string, unknown> = {}) {
  return {
    MonitoredVehicleJourney: {
      LineRef: { value: `STIF:Line::${line}:` },
      DestinationName: [{ value: dest }],
      MonitoredCall: {
        StopPointName: [{ value: "Châtelet" }],
        ExpectedDepartureTime: at(min),
        DepartureStatus: "onTime",
        VehicleAtStop: false,
        ...extra,
      },
    },
  };
}
const answer = (visits: unknown[]) => ({
  Siri: { ServiceDelivery: { StopMonitoringDelivery: [{ MonitoredStopVisit: visits }] } },
});

describe("lineIdOf", () => {
  it("reads the line code", () => {
    expect(lineIdOf("STIF:Line::C01374:")).toBe("C01374");
    expect(lineIdOf("nothing")).toBeNull();
  });
});

describe("parseStopMonitoring", () => {
  it("groups by line and destination, two times each, soonest first", () => {
    const rows = parseStopMonitoring(
      [
        answer([
          visit("C01374", "Bagneux", 7),
          visit("C01374", "Porte de Clignancourt", 4),
          visit("C01374", "Porte de Clignancourt", 1),
          visit("C01374", "Porte de Clignancourt", 9),
          visit("C01371", "La Défense", 2),
        ]),
      ],
      ["C01374", "C01371"],
      NOW,
    );
    expect(rows.map((r) => [r.line, r.dest, r.times.length])).toEqual([
      ["C01374", "Porte de Clignancourt", 2],
      ["C01371", "La Défense", 1],
      ["C01374", "Bagneux", 1],
    ]);
    expect(rows[0].times).toEqual([at(1), at(4)]);
  });

  it("drops other lines, cancelled, past, far ahead, unreadable and terminating trains", () => {
    const rows = parseStopMonitoring(
      [
        answer([
          visit("C00021", "Bus somewhere", 3),
          visit("C01374", "Bagneux", 3, { DepartureStatus: "cancelled" }),
          visit("C01374", "Bagneux", -5),
          visit("C01374", "Bagneux", 90),
          visit("C01374", "Bagneux", 3, { ExpectedDepartureTime: "soon" }),
          visit("C01374", "Châtelet", 3),
          visit("C01374", "Bagneux", 12),
        ]),
      ],
      ["C01374"],
      NOW,
    );
    expect(rows).toEqual([{ line: "C01374", dest: "Bagneux", times: [at(12)], atStop: false }]);
  });

  it("falls back to the arrival, then the aimed time, and reads VehicleAtStop", () => {
    const rows = parseStopMonitoring(
      [
        answer([
          visit("C01742", "Cergy le Haut", 0, {
            ExpectedDepartureTime: undefined,
            ExpectedArrivalTime: at(0),
            VehicleAtStop: true,
          }),
          visit("C01742", "Poissy", 6, { ExpectedDepartureTime: undefined, AimedDepartureTime: at(6) }),
        ]),
      ],
      ["C01742"],
      NOW,
    );
    expect(rows[0]).toEqual({ line: "C01742", dest: "Cergy le Haut", times: [at(0)], atStop: true });
    expect(rows[1].times).toEqual([at(6)]);
  });

  it("merges several stop areas without counting a train twice, and survives odd input", () => {
    const one = answer([visit("C01374", "Bagneux", 5)]);
    expect(parseStopMonitoring([one, one, null, "x", {}], ["C01374"], NOW)).toHaveLength(1);
    expect(parseStopMonitoring([one, one], ["C01374"], NOW)[0].times).toEqual([at(5)]);
  });
});

describe("minutesUntil, stillAhead", () => {
  it("counts whole minutes and never goes negative", () => {
    expect(minutesUntil(at(3), NOW)).toBe(3);
    expect(minutesUntil(at(0.9), NOW)).toBe(0);
    expect(minutesUntil(at(-2), NOW)).toBe(0);
    expect(minutesUntil("x", NOW)).toBeNull();
  });
  it("forgets departures that have left", () => {
    const rows = [
      { line: "a", dest: "A", times: [at(1), at(5)], atStop: true },
      { line: "b", dest: "B", times: [at(1)], atStop: false },
    ];
    const later = stillAhead(rows, NOW + 3 * 60_000);
    expect(later).toEqual([{ line: "a", dest: "A", times: [at(5)], atStop: false }]);
    expect(stillAhead(rows, NOW)).toEqual(rows);
  });
});

describe("isAnswer", () => {
  it("accepts the Worker's answer only", () => {
    expect(isAnswer({ status: "ok", now: at(0), rows: [] })).toBe(true);
    expect(isAnswer(null)).toBe(false);
    expect(isAnswer({ status: "ok" })).toBe(false);
  });
});
