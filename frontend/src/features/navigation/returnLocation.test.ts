import { describe, expect, it } from "vitest";

import {
  getAuxiliaryNavigationState,
  resolveReturnLocation,
} from "./returnLocation";

describe("navigation return location", () => {
  it("accepts each work route and preserves search and hash", () => {
    const sources = [
      { pathname: "/", search: "?project=7", hash: "#create" },
      { pathname: "/projects/7", search: "", hash: "#episodes" },
      {
        pathname: "/projects/7/episodes/8/script",
        search: "?tab=script",
        hash: "#editor",
      },
      {
        pathname: "/projects/7/episodes/8/assets",
        search: "?asset=11",
        hash: "",
      },
      {
        pathname: "/projects/7/episodes/8/shots",
        search: "",
        hash: "#shot-2",
      },
      {
        pathname: "/projects/7/episodes/8/director",
        search: "?clip=13",
        hash: "#review",
      },
      {
        pathname: "/projects/9007199254740991",
        search: "",
        hash: "",
      },
    ];

    sources.forEach((location) => {
      expect(resolveReturnLocation({ returnTo: location })).toEqual({
        kind: "valid",
        location,
      });
    });
  });

  it("rejects non-work, unsafe, and hostile source pathnames", () => {
    const invalidPathnames = [
      "/projects/0",
      "/projects/-1",
      "/projects/9007199254740992",
      "/projects/7/episodes/8",
      "/settings",
      "/tasks",
      "/unknown",
      "https://example.com/projects/7",
      "//example.com/projects/7",
      "javascript:alert(1)",
      "/projects\\7",
    ];

    invalidPathnames.forEach((pathname) => {
      expect(resolveReturnLocation({ returnTo: { pathname } })).toEqual({
        kind: "invalid",
      });
    });
  });

  it("rejects malformed source parts and does not read query returnTo", () => {
    expect(
      resolveReturnLocation({
        returnTo: {
          pathname: "/projects/7",
          search: "?returnTo=https://example.com",
          hash: "#safe",
        },
      }),
    ).toEqual({
      kind: "valid",
      location: {
        pathname: "/projects/7",
        search: "?returnTo=https://example.com",
        hash: "#safe",
      },
    });
    expect(
      resolveReturnLocation({
        returnTo: { pathname: "/projects/7", search: "returnTo=/tasks" },
      }),
    ).toEqual({ kind: "invalid" });
    expect(
      resolveReturnLocation({
        returnTo: { pathname: "/projects/7", hash: "#bad\\path" },
      }),
    ).toEqual({ kind: "invalid" });
  });

  it("distinguishes no source from a non-empty invalid state", () => {
    expect(resolveReturnLocation(undefined)).toEqual({ kind: "none" });
    expect(resolveReturnLocation(null)).toEqual({ kind: "none" });
    expect(resolveReturnLocation({})).toEqual({ kind: "none" });
    expect(resolveReturnLocation({ source: "/projects/7" })).toEqual({
      kind: "invalid",
    });
    expect(resolveReturnLocation("/projects/7")).toEqual({
      kind: "invalid",
    });
  });

  it("captures work locations and inherits the same state between auxiliary pages", () => {
    const workLocation = {
      pathname: "/projects/7/episodes/8/director",
      search: "?clip=13",
      hash: "#review",
    };
    const state = getAuxiliaryNavigationState(workLocation, {
      businessData: "not copied",
    });
    expect(state).toEqual({ returnTo: workLocation });

    const inherited = getAuxiliaryNavigationState(
      { pathname: "/settings", search: "", hash: "" },
      state,
    );
    expect(inherited).toBe(state);
    expect(
      getAuxiliaryNavigationState(
        { pathname: "/tasks", search: "", hash: "" },
        undefined,
      ),
    ).toBeUndefined();
  });
});
