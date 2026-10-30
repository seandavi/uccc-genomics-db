import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { FeasibilityPanel, Who } from "./App.tsx";

const render = (statement: string, copied = false) =>
  renderToStaticMarkup(<FeasibilityPanel statement={statement} copied={copied} onCopy={() => {}} onClose={() => {}} textareaRef={{current: null}} />);

describe("FeasibilityPanel", () => {
  test("an empty statement says it is recounting: no textarea, Copy disabled, Close offered", () => {
    const html = render("");
    expect(html).toContain("Recounting…");
    expect(html).not.toContain("<textarea");
    expect(html).toMatch(/<button type="button" disabled="">Copy<\/button>/);
    expect(html).toContain(">Close</button>");
  });
  test("a statement is in a textarea and Copy is enabled", () => {
    const html = render("About 40 patients a year.");
    expect(html).toMatch(/<textarea[^>]*>About 40 patients a year\.<\/textarea>/);
    expect(html).not.toContain("Recounting");
    expect(html).toContain('<button type="button">Copy</button>');
  });
  test("copied is announced", () => {
    expect(render("x", true)).toContain("Copied");
    expect(render("x")).not.toContain("Copied");
  });
});

describe("Who", () => {
  const html = (sign_out: boolean) =>
    renderToStaticMarkup(<Who me={{sub: "s", email: "a@example.edu", sign_out}} onSignOut={() => {}} />);
  test("shows the email and, when the backend has a session, Sign out", () => {
    expect(html(true)).toContain('<span class="sr-only">Signed in as </span>a@example.edu');
    expect(html(true)).toContain(">Sign out</button>");
  });
  test("no Sign out button without a session", () => {
    expect(html(false)).toContain("a@example.edu");
    expect(html(false)).not.toContain("Sign out");
  });
});
