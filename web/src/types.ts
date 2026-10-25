import type { components } from "./api.gen.ts";

type S = components["schemas"];
export type Definition = S["Definition"];
export type Population = S["Population"];
export type Criterion = Definition["criteria"][number];
export type Leaf = S["AnyOf"]["of"][number];
export type Operation = S["ApplyRequest"]["op"];
export type ApplyResult = S["ApplyResult"];
export type CountResult = S["CountResult"];
export type PivotResult = S["PivotResult"];
export type Options = S["Options"];
export type Option = S["Option"];
export type BreakdownDim = Definition["breakdown"][number];
