// Tiny Node script: runs the pattern engine once and prints the result as JSON.
//
// Usage:   node bridge.js <path to engine script>
// Input:   one JSON object on stdin, e.g. {"op": "check", "code": "..."}
// Output:  one JSON object on stdout.
//
// Why a "vm context"? The engine script is written for a web browser: it is a
// big pile of global functions, not a module. We load it into an isolated
// sandbox (vm) so those globals don't leak, and we give it the few browser
// things it expects (alert, console).

const fs = require("fs");
const vm = require("vm");

const enginePath = process.argv[2];
const request = JSON.parse(fs.readFileSync(0, "utf8"));

// The engine reports warnings by calling alert(). We collect them instead.
const warnings = [];
const sandbox = {
  console: { log() {}, warn() {}, error() {}, time() {}, timeEnd() {} },
  alert: (msg) => warnings.push(String(msg)),
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(enginePath, "utf8"), sandbox, { filename: "engine.js" });

function check(code) {
  try {
    // Parses the pattern. Throws an Error if the pattern is invalid.
    // The second argument is an optional layout; "" means none.
    sandbox.processText(code, "");
  } catch (e) {
    return { ok: false, error: String(e && e.message ? e.message : e), warnings };
  }
  // The engine leaves its parsed stitch list in a global. Keep only plain fields.
  const stitches = sandbox.Stitches.map((s) => ({
    row: s.nrow,           // row/round number as the engine counts it (0 = start)
    type: s.type,          // stitch name, e.g. "sc", "sc2inc", "ring"
    ids: s.id,             // ids of the loops this stitch creates
    attach: s.id_attach,   // ids of the earlier loops it is worked into
    explicit: s.attach_ref !== null && s.attach_ref !== undefined, // has an @label
    labels: s.label || [], // names the pattern gave this stitch (e.g. "ch.A")
  }));
  return { ok: true, error: null, warnings, stitches };
}

let response;
if (request.op === "check") {
  response = check(String(request.code));
} else {
  response = { ok: false, error: "unknown op: " + request.op, warnings };
}
process.stdout.write(JSON.stringify(response));
