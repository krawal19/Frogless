// The page's calls to the Frogless API.
async function call(url, options) {
  const res = await fetch(url, options);
  let body = null;
  try { body = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok) {
    const detail = body && body.detail;
    throw new Error(typeof detail === "string" ? detail : `The server answered ${res.status}.`);
  }
  return body;
}

const Api = {
  examples: () => call("/api/examples"),
  check: (text, terms) => call("/api/check", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, terms }),
  }),
  render: (id, size) => call(`/api/render/${id}?size=${size}`, { method: "POST" }),
};

Object.assign(window, { Api });
