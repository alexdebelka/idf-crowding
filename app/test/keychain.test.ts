import { describe, expect, it } from "vitest";
import { KEYCHAIN_MAX, keychainLink } from "@/lib/keychain";

const p = (id: string) => ({ id, name: id });

describe("keychainLink", () => {
  it("lists the ids in order", () => {
    expect(keychainLink([p("71264"), p("412687")])).toBe("http://192.168.4.1/f?ids=71264,412687");
  });
  it("is null without favourites", () => {
    expect(keychainLink([])).toBeNull();
  });
  it("drops ids the keychain refuses and keeps at most the keychain's maximum", () => {
    const many = Array.from({ length: 20 }, (_, i) => p(String(1000 + i)));
    const link = keychainLink([p("bad id"), p("x".repeat(16)), ...many]);
    expect(link?.split("=")[1].split(",")).toHaveLength(KEYCHAIN_MAX);
    expect(link).not.toContain("bad");
  });
});
