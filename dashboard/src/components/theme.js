// Colors and formatters shared by every page, so vendors and alteration classes
// look the same everywhere.
// Internal vendor keys stay "caris"/"fmi"; readers see the spelled-out name.
export const vendorLabel = {caris: "Caris", fmi: "Foundation Medicine (FMI)"};
export const vendorColor = {domain: ["caris", "fmi"], range: ["#2a78d6", "#eb6834"], legend: true, tickFormat: (d) => (d === "fmi" ? "FMI" : "Caris")};
export const altColor = {
  domain: ["pathogenic/likely", "amplification", "loss", "fusion", "VUS"],
  range: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
  legend: true
};
export const assayColor = {domain: ["tissue", "liquid", "heme"], range: ["#2a78d6", "#1baf7a", "#9c59b6"], legend: true};
export const fmt = (n) => (n == null ? "–" : Number(n).toLocaleString("en-US"));
export const pct = (x, digits = 1) => (x == null || !isFinite(x) ? "–" : (x * 100).toFixed(digits) + "%");
