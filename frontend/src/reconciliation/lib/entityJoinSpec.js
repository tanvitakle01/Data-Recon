// Which entities a side should fetch, and how to join them — normalized into
// ONE shape from the two paths that can produce it, with the precedence rule
// living here only:
//
//   1. Free text typed on Step 1 (state.entityJoin[role].parsed) — WINS when
//      present, because typing it is a deliberate override.
//   2. Whatever the mapping-sheet identification derived for that side.
//
// Both paths are already existence-gated server-side against the live entity
// list of that side's own connector, so anything in `entities` here is a real,
// fetchable entity on that side and `unresolved` is what was named but doesn't
// exist (flagged for the human, never silently placed).
//
// `joinType`/`keys` are null unless the sheet or the user actually stated them.
// That's deliberate: the Join Builder canvas applies its own single default
// (left join, keys mirrored from the relationship's suggested keys), and this
// layer must not introduce a competing default policy.

const EMPTY = {
  entities: [],
  primary: null,
  joinType: null,
  keys: null,
  unresolved: [],
  planningArea: null,
  ambiguous: [],
};

function normalize(spec, origin) {
  if (!spec) return null;
  const entities = spec.entities ?? [];
  const unresolved = spec.unresolved ?? spec.unresolved_entities ?? [];
  const ambiguous = spec.ambiguous ?? spec.ambiguous_entities ?? [];
  // Nothing named, nothing flagged, nothing tied → nothing to say about this side.
  if (entities.length === 0 && unresolved.length === 0 && ambiguous.length === 0) return null;
  return {
    ...EMPTY,
    entities,
    primary: spec.primary ?? spec.primary_entity ?? entities[0] ?? null,
    joinType: spec.join_type ?? null,
    keys: spec.keys ?? spec.join_keys ?? null,
    unresolved,
    ambiguous,
    planningArea: spec.planning_area ?? null,
    origin,
    // How the entity was determined server-side: "sheet" (named outright),
    // "fields" (matched from the sheet's field list against live metadata), or
    // null. Free text is always "typed" — the user named it themselves.
    entitySource: origin === "freeText" ? "typed" : spec.entity_source ?? null,
    entityEvidence: spec.entity_evidence ?? "",
  };
}

// Settle a tie using a planning area the user picked by hand.
//
// When the sheet's fields matched the same planning level in several planning
// areas, the backend refused to choose and returned the candidates. Those are
// already live, existence-gated entity names, so narrowing them by the area the
// human selected decides between them without inventing anything. A choice that
// still leaves 0 or 2+ candidates changes nothing — it stays unresolved.
export function applyPlanningArea(spec, area) {
  if (!spec || !area || spec.entities.length > 0 || spec.ambiguous.length === 0) return spec;
  const norm = (v) => String(v).toLowerCase().replace(/[^a-z0-9]/g, "");
  const needle = norm(area);
  const hits = spec.ambiguous.filter((e) => norm(e).includes(needle));
  if (hits.length !== 1) return { ...spec, planningArea: area };
  return {
    ...spec,
    entities: hits,
    primary: hits[0],
    ambiguous: [],
    planningArea: area,
    entitySource: "area",
    entityEvidence: `Narrowed to ${hits[0]} by the planning area you selected (${area}).`,
  };
}

// The sheet-derived entity/join for one side, or null if the sheet said nothing.
export function sheetEntityJoin(identification, role) {
  return normalize(identification?.[role], "sheet");
}

// The free-text-derived entity/join for one side, or null if none was resolved.
export function freeTextEntityJoin(entityJoin, role) {
  return normalize(entityJoin?.[role]?.parsed, "freeText");
}

// The spec that should actually pre-populate the canvas for this side.
// Free text overrides the sheet; a hand-picked planning area then settles any
// tie the sheet left behind. Null means "leave the canvas alone".
export function effectiveEntityJoin(state, role) {
  const spec =
    freeTextEntityJoin(state?.entityJoin, role) ??
    sheetEntityJoin(state?.sheetIdentification, role);
  return applyPlanningArea(spec, state?.entityJoin?.[role]?.planningArea);
}

// How the join will be configured on the canvas, with each part marked as
// STATED (the sheet/instruction said so) or DEFAULT (unspecified — the canvas
// applies its own default). Kept here so the Step-1 details and the canvas can
// never disagree about what the default is.
export function joinSummary(spec) {
  if (!spec || spec.entities.length < 2) return null;
  const typeStated = Boolean(spec.joinType);
  const keyPairs = spec.keys ?? [];
  const keysStated = keyPairs.length > 0;
  return {
    typeLabel: (spec.joinType ?? "left").replace(/^./, (c) => c.toUpperCase()),
    typeStated,
    // Default keys aren't knowable until the canvas loads the connector's
    // relationship metadata, so say that plainly rather than invent names.
    keysLabel: keysStated
      ? keyPairs.map((k) => (k.left === k.right ? k.left : `${k.left} = ${k.right}`)).join(", ")
      : "the keys the connector suggests for this relationship",
    keysStated,
  };
}

// Where a side's entities came from, in one human phrase.
export function describeEntitySource(spec) {
  if (!spec) return "";
  switch (spec.entitySource) {
    case "typed":
      return "From your typed instruction";
    case "sheet":
      return "Named in the mapping sheet";
    case "fields":
      return "Matched from the fields the mapping sheet lists";
    case "area":
      return "Narrowed by the planning area you selected";
    default:
      return "";
  }
}

// One-line human summary of a spec, for the Step-1 confirmation text.
export function describeEntityJoin(spec) {
  if (!spec) return "";
  const parts = [];
  if (spec.entities.length > 0) {
    parts.push(
      spec.entities.length === 1
        ? `Use ${spec.entities[0]}`
        : `Join ${spec.entities.join(" + ")}`
    );
  }
  if (spec.entities.length > 1) {
    parts.push(`${spec.joinType ?? "left (canvas default)"} join`);
    const keys = (spec.keys ?? []).map((k) => (k.left === k.right ? k.left : `${k.left} = ${k.right}`));
    parts.push(keys.length > 0 ? `on ${keys.join(", ")}` : "on the canvas's suggested keys");
  }
  return parts.join(" · ");
}
