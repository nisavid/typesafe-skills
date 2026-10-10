// Make one uncached request through the locked evaluator with retries disabled.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

try {
  const [cli, questionsPath, statePath, model] = process.argv.slice(2);
  if (process.argv.length !== 6 || model !== "jev-1.13.0") throw new Error("invalid inputs");
  const entry = pathToFileURL(cli);
  const { evaluate } = await import(new URL("../src/client.js", entry));
  const questions = JSON.parse(readFileSync(questionsPath, "utf8"));
  const state = JSON.parse(readFileSync(statePath, "utf8"));
  const result = await evaluate(state, questions, { command: "ask", model, cache: false, maxRetries: 0 });
  const ids = Object.keys(questions);
  // Machine evidence retains provider precision; display formatters round these fields.
  const output = {
    answers: ids.map((id) => ({ id, type: result.answers[id].type,
      answer: result.answers[id].choice, confidence: result.answers[id].confidence })),
    distributions: Object.fromEntries(ids.map((id) => [id,
      Object.entries(result.answers[id].probabilities).map(([option, p]) => ({ option, p }))])),
    raw: [{ model: result.model, answers: result.answers, usage: result.usage,
      ms: result.ms, cached: result.cached }],
  };
  process.stdout.write(JSON.stringify(output) + "\n");
} catch {
  // Provider diagnostics can contain credentials or source material; Python emits a fixed hold reason.
  process.stderr.write("Jev input or transport error\n");
  process.exitCode = 1;
}
