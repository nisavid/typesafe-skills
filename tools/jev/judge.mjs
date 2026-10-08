// Make one uncached request through the locked evaluator with retries disabled.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

try {
  const [cli, questionsPath, statePath, model] = process.argv.slice(2);
  if (process.argv.length !== 6 || model !== "jev-1.13.0") throw new Error("invalid inputs");
  const entry = pathToFileURL(cli);
  const { evaluate } = await import(new URL("../src/client.js", entry));
  const { answerRow, distributionRows } = await import(new URL("../src/format.js", entry));
  const { finish, thresholdsFrom } = await import(new URL("../src/commands/common.js", entry));
  const questions = JSON.parse(readFileSync(questionsPath, "utf8"));
  const state = JSON.parse(readFileSync(statePath, "utf8"));
  const result = await evaluate(state, questions, { command: "ask", model, cache: false, maxRetries: 0 });
  const parsed = { values: {}, bools: { "--json": true } };
  const thresholds = thresholdsFrom(parsed);
  const ids = Object.keys(questions);
  const output = {
    answers: ids.map((id) => answerRow(id, result.answers[id], thresholds)),
    distributions: Object.fromEntries(ids.map((id) => [id, distributionRows(result.answers[id])])),
  };
  process.stdout.write(finish(parsed, output, [result]) + "\n");
} catch {
  // Provider diagnostics can contain credentials or source material; Python emits a fixed hold reason.
  process.stderr.write("Jev input or transport error\n");
  process.exitCode = 1;
}
