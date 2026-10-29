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

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// Checks and drawings run as jobs on the server: start one, then ask for its state until it is no longer running.
// onJob(id) is called once the job has an id (so Stop can end it). Resolves with the result, or null when it was stopped.
async function runJob(start, onJob) {
  const { job } = await start();
  if (onJob) onJob(job);
  for (;;) {
    await wait(700);
    const j = await call(`/api/job/${job}`);
    if (j.state === "running") continue;
    if (j.state === "stopped") return null;
    if (j.state === "error") throw new Error(j.error || "The work failed.");
    return j.result;
  }
}

const Api = {
  examples: () => call("/api/examples"),
  check: (text, terms, onJob) => runJob(() => call("/api/check", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, terms }),
  }), onJob),
  render: (id, size, onJob) => runJob(() => call(`/api/render/${id}?size=${size}`, { method: "POST" }), onJob),
  stop: (job) => call(`/api/stop/${job}`, { method: "POST" }),
};

Object.assign(window, { Api });
