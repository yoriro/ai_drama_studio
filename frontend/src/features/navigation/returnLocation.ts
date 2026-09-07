export interface NavigationLocation {
  pathname: string;
  search: string;
  hash: string;
}

export interface ReturnLocation {
  pathname: string;
  search: string;
  hash: string;
}

export type ReturnLocationDecision =
  | { kind: "none" }
  | { kind: "invalid" }
  | { kind: "valid"; location: ReturnLocation };

interface RecordValue {
  [key: string]: unknown;
}

export function resolveReturnLocation(
  state: unknown,
): ReturnLocationDecision {
  if (state === null || state === undefined) {
    return { kind: "none" };
  }

  if (isRecordValue(state) && Object.keys(state).length === 0) {
    return { kind: "none" };
  }

  if (
    !isRecordValue(state) ||
    !Object.prototype.hasOwnProperty.call(state, "returnTo")
  ) {
    return { kind: "invalid" };
  }

  const source = state.returnTo;
  if (!isRecordValue(source) || typeof source.pathname !== "string") {
    return { kind: "invalid" };
  }

  const search = source.search === undefined ? "" : source.search;
  const hash = source.hash === undefined ? "" : source.hash;
  if (
    typeof search !== "string" ||
    typeof hash !== "string" ||
    !isWorkPathname(source.pathname) ||
    !isQueryPart(search) ||
    !isHashPart(hash) ||
    source.pathname.includes("\\") ||
    search.includes("\\") ||
    hash.includes("\\")
  ) {
    return { kind: "invalid" };
  }

  return {
    kind: "valid",
    location: { pathname: source.pathname, search, hash },
  };
}

export function getAuxiliaryNavigationState(
  location: NavigationLocation,
  state: unknown,
): unknown {
  if (isWorkPathname(location.pathname)) {
    return {
      returnTo: {
        pathname: location.pathname,
        search: location.search,
        hash: location.hash,
      },
    };
  }

  if (location.pathname === "/settings" || location.pathname === "/tasks") {
    return state;
  }

  return undefined;
}

function isRecordValue(value: unknown): value is RecordValue {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isQueryPart(value: string): boolean {
  return value === "" || value.startsWith("?");
}

function isHashPart(value: string): boolean {
  return value === "" || value.startsWith("#");
}

function isWorkPathname(pathname: string): boolean {
  if (pathname === "/") {
    return true;
  }

  const projectMatch = /^\/projects\/([0-9]+)$/.exec(pathname);
  if (projectMatch !== null) {
    return isPositiveSafeIntegerSegment(projectMatch[1]);
  }

  const episodeMatch =
    /^\/projects\/([0-9]+)\/episodes\/([0-9]+)\/(script|assets|shots|director)$/.exec(
      pathname,
    );
  return (
    episodeMatch !== null &&
    isPositiveSafeIntegerSegment(episodeMatch[1]) &&
    isPositiveSafeIntegerSegment(episodeMatch[2])
  );
}

function isPositiveSafeIntegerSegment(segment: string): boolean {
  const value = Number(segment);
  return Number.isSafeInteger(value) && value > 0;
}
