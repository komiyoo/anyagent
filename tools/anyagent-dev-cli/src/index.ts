#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

type JsonError = {
  code: string;
  message: string;
};

type CliOptions = {
  json: boolean;
  root: string;
};

type VersionSource = {
  path: string;
  label: string;
  pattern: RegExp;
};

type LoadedVersionSource = VersionSource & {
  absolutePath: string;
  text: string;
  currentVersion: string;
};

const VERSION_SOURCES: VersionSource[] = [
  {
    path: "packages/anyagent/pyproject.toml",
    label: "project.version",
    pattern: /^(version = ")([^"]+)(")$/m,
  },
  {
    path: "packages/anyagent/src/anyagent/__init__.py",
    label: "anyagent.__version__",
    pattern: /^(__version__ = ")([^"]+)(")$/m,
  },
  {
    path: "packages/anyagent/src/anyagent/tool_runtime/__init__.py",
    label: "anyagent.tool_runtime.__version__",
    pattern: /^(__version__ = ")([^"]+)(")$/m,
  },
  {
    path: "packages/anyagent/src/anyagent/server/app.py",
    label: "server FastAPI version",
    pattern: /(FastAPI\(title="anyagent", version=")([^"]+)(")/,
  },
  {
    path: "packages/anyagent/src/anyagent/tool_runtime/server.py",
    label: "tool runtime FastAPI version",
    pattern: /(FastAPI\(title="anyagent-tool-runtime", version=")([^"]+)(")/,
  },
];

const SEMVER_RE = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$/;
const DEFAULT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

class CliError extends Error {
  code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

function usage(): string {
  return [
    "anyagent-dev-cli <command> [options]",
    "",
    "Commands:",
    "  doctor [--json]                  Check repo-bound CLI setup",
    "  version show [--json]            Show framework version sources",
    "  version bump <version> [options] Bump framework version sources",
    "",
    "Options:",
    "  --root <path>  Repository root; defaults to this CLI's repository",
    "  --json         Emit stable JSON envelope instead of Markdown",
    "  --dry-run      Validate and print planned writes without changing files",
    "  -h, --help     Show help",
  ].join("\n");
}

function parseGlobalArgs(argv: string[]): { args: string[]; options: CliOptions } {
  const args: string[] = [];
  const options: CliOptions = { json: false, root: DEFAULT_ROOT };

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "--json") {
      options.json = true;
    } else if (arg === "--root") {
      const value = argv[index + 1];
      if (!value) {
        throw new CliError("missing_root", "--root requires a path");
      }
      options.root = value;
      index += 1;
    } else {
      args.push(arg);
    }
  }

  options.root = path.resolve(options.root);
  return { args, options };
}

function printJson(data: unknown): void {
  process.stdout.write(`${JSON.stringify({ ok: true, data }, null, 2)}\n`);
}

function printJsonError(error: JsonError): void {
  process.stdout.write(`${JSON.stringify({ ok: false, error }, null, 2)}\n`);
}

function markdownTable(headers: string[], rows: string[][]): string {
  const widths = headers.map((header, index) => {
    const rowWidths = rows.map((row) => row[index]?.length ?? 0);
    return Math.max(header.length, ...rowWidths);
  });
  const renderRow = (row: string[]) => `| ${row.map((cell, index) => cell.padEnd(widths[index] ?? 0)).join(" | ")} |`;
  const divider = `| ${widths.map((width) => "-".repeat(width)).join(" | ")} |`;
  return [renderRow(headers), divider, ...rows.map(renderRow)].join("\n");
}

function loadVersionSource(root: string, source: VersionSource): LoadedVersionSource {
  const absolutePath = path.join(root, source.path);
  if (!fs.existsSync(absolutePath)) {
    throw new CliError("missing_version_source", `${source.path}: missing version source`);
  }

  const text = fs.readFileSync(absolutePath, "utf8");
  const matches = [...text.matchAll(new RegExp(source.pattern.source, source.pattern.flags.includes("g") ? source.pattern.flags : `${source.pattern.flags}g`))];
  if (matches.length !== 1) {
    throw new CliError(
      "version_source_match_count",
      `${source.path}: expected exactly one ${source.label} match, found ${matches.length}`,
    );
  }

  const currentVersion = matches[0]?.[2];
  if (!currentVersion) {
    throw new CliError("version_source_parse_failed", `${source.path}: could not parse version`);
  }

  return { ...source, absolutePath, text, currentVersion };
}

function loadVersionSources(root: string): LoadedVersionSource[] {
  const loaded = VERSION_SOURCES.map((source) => loadVersionSource(root, source));
  const versions = new Set(loaded.map((source) => source.currentVersion));
  if (versions.size !== 1) {
    const details = loaded.map((source) => `${source.path}=${source.currentVersion}`).join(", ");
    throw new CliError("version_sources_disagree", `version sources disagree: ${details}`);
  }
  return loaded;
}

function replaceVersion(source: LoadedVersionSource, newVersion: string): string {
  let replacements = 0;
  const updated = source.text.replace(source.pattern, (match, prefix: string, _current: string, suffix: string) => {
    replacements += 1;
    return `${prefix}${newVersion}${suffix}`;
  });

  if (replacements !== 1) {
    throw new CliError(
      "version_replacement_count",
      `${source.path}: expected one replacement, replaced ${replacements}`,
    );
  }
  return updated;
}

function commandDoctor(options: CliOptions): void {
  const packageJson = path.join(options.root, "tools/anyagent-dev-cli/package.json");
  const distIndex = path.join(options.root, "tools/anyagent-dev-cli/dist/index.js");
  const data = {
    root: options.root,
    authRequired: false,
    packageJsonExists: fs.existsSync(packageJson),
    built: fs.existsSync(distIndex),
    versionSourceCount: VERSION_SOURCES.length,
    versionSources: VERSION_SOURCES.map((source) => source.path),
  };

  if (options.json) {
    printJson(data);
    return;
  }

  console.log("**anyagent-dev-cli doctor**");
  console.log("");
  console.log(`- Root: \`${data.root}\``);
  console.log(`- Auth required: ${data.authRequired ? "yes" : "no"}`);
  console.log(`- Package: ${data.packageJsonExists ? "ok" : "missing"}`);
  console.log(`- Build: ${data.built ? "ok" : "missing; run `npm --prefix tools/anyagent-dev-cli run build`"}`);
  console.log(`- Version sources: ${data.versionSourceCount}`);
}

function commandVersionShow(options: CliOptions): void {
  const sources = loadVersionSources(options.root);
  const currentVersion = sources[0]?.currentVersion ?? "";
  const data = {
    currentVersion,
    sources: sources.map((source) => ({
      path: source.path,
      label: source.label,
      version: source.currentVersion,
    })),
  };

  if (options.json) {
    printJson(data);
    return;
  }

  console.log(`**anyagent version: ${currentVersion}**`);
  console.log("");
  console.log(markdownTable(
    ["Source", "Version", "Label"],
    data.sources.map((source) => [source.path, source.version, source.label]),
  ));
}

function commandVersionBump(args: string[], options: CliOptions): void {
  const dryRun = args.includes("--dry-run");
  const filteredArgs = args.filter((arg) => arg !== "--dry-run");
  const newVersion = filteredArgs[0]?.trim();
  if (!newVersion) {
    throw new CliError("missing_version", "version bump requires <version>");
  }
  if (!SEMVER_RE.test(newVersion)) {
    throw new CliError("invalid_version", `invalid semantic version: ${newVersion}`);
  }

  const sources = loadVersionSources(options.root);
  const currentVersion = sources[0]?.currentVersion ?? "";
  const changes = sources.map((source) => ({
    path: source.path,
    label: source.label,
    from: source.currentVersion,
    to: newVersion,
  }));

  if (currentVersion === newVersion) {
    const data = { currentVersion, newVersion, dryRun, changed: false, changes: [] };
    if (options.json) {
      printJson(data);
    } else {
      console.log(`**anyagent version already ${newVersion}**`);
      console.log("");
      console.log("No changes needed.");
    }
    return;
  }

  for (const source of sources) {
    const updated = replaceVersion(source, newVersion);
    if (!dryRun) {
      fs.writeFileSync(source.absolutePath, updated, "utf8");
    }
  }

  const data = { currentVersion, newVersion, dryRun, changed: !dryRun, changes };
  if (options.json) {
    printJson(data);
    return;
  }

  console.log(`**version bump ${currentVersion} -> ${newVersion}${dryRun ? " (dry-run)" : ""}**`);
  console.log("");
  console.log(markdownTable(
    ["Source", "From", "To"],
    changes.map((change) => [change.path, change.from, change.to]),
  ));
}

function main(argv: string[]): number {
  const { args, options } = parseGlobalArgs(argv);
  const [command, subcommand, ...rest] = args;

  if (!command || command === "-h" || command === "--help") {
    console.log(usage());
    return 0;
  }

  if (command === "doctor") {
    commandDoctor(options);
    return 0;
  }

  if (command === "version" && subcommand === "show") {
    commandVersionShow(options);
    return 0;
  }

  if (command === "version" && subcommand === "bump") {
    commandVersionBump(rest, options);
    return 0;
  }

  throw new CliError("unknown_command", `unknown command: ${args.join(" ")}`);
}

try {
  process.exitCode = main(process.argv.slice(2));
} catch (error) {
  const parsed = parseGlobalArgs(process.argv.slice(2));
  const cliError = error instanceof CliError
    ? error
    : new CliError("unexpected_error", error instanceof Error ? error.message : String(error));
  if (parsed.options.json) {
    printJsonError({ code: cliError.code, message: cliError.message });
  } else {
    console.error(`error: ${cliError.message}`);
  }
  process.exitCode = cliError.code === "invalid_version" ? 2 : 1;
}
