// Runs only for /api/* (run_worker_first in wrangler.toml). Access has already let the user in
// on this hostname; forward the request, cookie and Cf-Access-Jwt-Assertion included, to the
// cohort API on the campus host, which verifies that JWT itself.
const API = "https://uccc-genomics-api.cancerdatasci.org";

export default {
  fetch(request) {
    const url = new URL(request.url);
    return fetch(new Request(API + url.pathname + url.search, request));
  },
};
