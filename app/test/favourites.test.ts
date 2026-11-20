// Favourite stations: stored list, toggle, home sections, and the service worker's side.
import { describe, expect, it } from "vitest";
import { homeSections } from "../src/components/home/logic";
import { MAX_FAVOURITES, parseFavourites, recentOnly, toggleIn } from "../src/lib/favourites";

const p = (id: string) => ({ id, name: `Gare ${id}` });

describe("parseFavourites", () => {
  it("keeps valid entries in order, without duplicates", () => {
    expect(parseFavourites([p("a"), p("b"), p("a")])).toEqual([p("a"), p("b")]);
  });
  it("drops invalid values", () => {
    expect(parseFavourites(null)).toEqual([]);
    expect(parseFavourites({ id: "a" })).toEqual([]);
    expect(parseFavourites([{ id: "a" }, { id: 3, name: "x" }, { id: "../x", name: "x" }, p("ok")])).toEqual([p("ok")]);
  });
  it("keeps id and name only, at most the maximum", () => {
    expect(parseFavourites([{ ...p("a"), extra: 1 }])).toEqual([p("a")]);
    const many = Array.from({ length: 20 }, (_, i) => p(String(i)));
    expect(parseFavourites(many)).toHaveLength(MAX_FAVOURITES);
  });
});

describe("toggleIn", () => {
  it("adds at the end, removes when present", () => {
    const added = toggleIn([p("a")], p("b"));
    expect(added).toEqual({ list: [p("a"), p("b")], result: "added" });
    expect(toggleIn(added.list, p("a"))).toEqual({ list: [p("b")], result: "removed" });
  });
  it("refuses a new station when full, still removes one", () => {
    const full = [p("a"), p("b")];
    expect(toggleIn(full, p("c"), 2)).toEqual({ list: full, result: "full" });
    expect(toggleIn(full, p("a"), 2).result).toBe("removed");
  });
});

describe("home sections", () => {
  const big = [p("x"), p("y")];
  it("favourites first, then recent stations that are not favourites", () => {
    const s = homeSections([p("a")], [p("b"), p("a"), p("c")], big);
    expect(s.map((x) => x.kind)).toEqual(["favourites", "recent"]);
    expect(s[1].stations.map((x) => x.id)).toEqual(["b", "c"]);
  });
  it("no recent section when every recent station is a favourite", () => {
    expect(homeSections([p("a")], [p("a")], big).map((x) => x.kind)).toEqual(["favourites"]);
  });
  it("recent only, then the largest stations when the device has nothing", () => {
    expect(homeSections([], [p("b")], big).map((x) => x.kind)).toEqual(["recent"]);
    expect(homeSections([], [], big)).toEqual([{ kind: "big", stations: big }]);
  });
  it("recentOnly caps the list", () => {
    expect(recentOnly([p("a"), p("b"), p("c")], [p("b")], 1)).toEqual([p("a")]);
  });
});
