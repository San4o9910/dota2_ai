import {readdir,readFile} from "node:fs/promises";
import {DatabaseSync} from "node:sqlite";
function statements(source) {
  return source
    .split("--> statement-breakpoint")
    .map((statement) => statement.trim())
    .filter(Boolean);
}

function executeSqliteStatement(statement, method, source, bindings) {
  const numberedParameters = [...source.matchAll(/\?(\d+)/g)];
  if (numberedParameters.length === 0) return statement[method](...bindings);
  const values = {};
  for (const [, index] of numberedParameters) values[index] = bindings[Number(index) - 1];
  return statement[method](values);
}

class SqliteD1Statement {
  constructor(database, source, bindings = []) {
    this.database = database;
    this.source = source;
    this.bindings = bindings;
  }

  bind(...bindings) {
    return new SqliteD1Statement(this.database, this.source, bindings);
  }

  async first() {
    const statement = this.database.prepare(this.source);
    return executeSqliteStatement(statement, "get", this.source, this.bindings) ?? null;
  }

  async all() {
    const statement = this.database.prepare(this.source);
    return {
      success: true,
      results: executeSqliteStatement(statement, "all", this.source, this.bindings),
    };
  }

  async run() {
    const statement = this.database.prepare(this.source);
    const result = executeSqliteStatement(statement, "run", this.source, this.bindings);
    return { success: true, results: [], meta: { changes: Number(result.changes) } };
  }
}

class SqliteD1 {
  constructor(database) {
    this.database = database;
  }

  prepare(source) {
    return new SqliteD1Statement(this.database, source);
  }

  async batch(batchStatements) {
    this.database.exec("BEGIN IMMEDIATE");
    try {
      const results = [];
      // D1 executes the entire batch atomically and preserves RETURNING rows.
      // Keep this synchronous SQLite transaction from yielding to another batch.
      for (const statement of batchStatements) {
        const prepared=this.database.prepare(statement.source);
        const returning=/\bRETURNING\b/i.test(statement.source);
        const result=executeSqliteStatement(prepared,returning ? "all" : "run",statement.source,statement.bindings);
        results.push({success:true,results:returning ? result : [],meta:{changes:Number(this.database.prepare("SELECT changes() AS count").get().count)}});
      }
      this.database.exec("COMMIT");
      return results;
    } catch (error) {
      this.database.exec("ROLLBACK");
      throw error;
    }
  }
}

export async function database() {
  const sqlite = new DatabaseSync(":memory:");
  sqlite.exec("PRAGMA foreign_keys=ON");
  const migrationDirectory = new URL("../drizzle/", import.meta.url);
  const names = (await readdir(migrationDirectory))
    .filter((name) => /^\d{4}_.+\.sql$/.test(name))
    .sort();
  for (const name of names) {
    const source = await readFile(new URL(name, migrationDirectory), "utf8");
    sqlite.exec("BEGIN");
    try {
      for (const statement of statements(source)) sqlite.exec(statement);
      sqlite.exec("COMMIT");
    } catch (error) {
      sqlite.exec("ROLLBACK");
      throw error;
    }
  }
  return { sqlite, d1: new SqliteD1(sqlite) };
}

