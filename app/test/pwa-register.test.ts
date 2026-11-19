import { describe, expect, it } from "vitest";
import { shouldRegister, stationIdOfPath } from "@/components/pwa/register";

describe("shouldRegister", () => {
  const base = { nodeEnv: "production", hasServiceWorker: true, secureContext: true };
  it("registers in production, in a secure context", () => expect(shouldRegister(base)).toBe(true));
  it("not in development or test", () => {
    expect(shouldRegister({ ...base, nodeEnv: "development" })).toBe(false);
    expect(shouldRegister({ ...base, nodeEnv: "test" })).toBe(false);
    expect(shouldRegister({ ...base, nodeEnv: undefined })).toBe(false);
  });
  it("not without support or outside a secure context", () => {
    expect(shouldRegister({ ...base, hasServiceWorker: false })).toBe(false);
    expect(shouldRegister({ ...base, secureContext: false })).toBe(false);
  });
});

describe("stationIdOfPath", () => {
  it("reads the id of a station page path", () => {
    expect(stationIdOfPath("/p/71264/")).toBe("71264");
    expect(stationIdOfPath("/p/71264")).toBe("71264");
  });
  it("is null elsewhere", () => {
    for (const p of ["/", "/a-propos/", "/p/", "/p/1/2/", "/p/..%2Fx/", "/data/places/1.json"]) {
      expect(stationIdOfPath(p), p).toBeNull();
    }
  });
});
