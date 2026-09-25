// Runs only for /api/* (run_worker_first in wrangler.toml): on a zone route, fetch(request)
// goes to the origin, Traefik on the campus host, and on to the cohort API. Access has
// already authenticated the request and added Cf-Access-Jwt-Assertion, which the API checks.
export default {fetch: (request) => fetch(request)};
