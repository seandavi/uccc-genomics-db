import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Checks } from "./Builder.tsx";

describe("Checks", () => {
  test("a failed value load says so in an alert", () => {
    const html = renderToStaticMarkup(<Checks legend="Site" values={[]} selected={[]} onChange={() => {}} error="request failed (500)" />);
    expect(html).toContain('role="alert"');
    expect(html).toContain("Could not load values: request failed (500)");
  });
  test("no error, no alert", () => {
    expect(renderToStaticMarkup(<Checks legend="Site" values={["a"]} selected={[]} onChange={() => {}} />)).not.toContain("alert");
  });
});
