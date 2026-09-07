import assert from "node:assert/strict";
import test from "node:test";

import { verifyD1PackageContract } from "../scripts/verify-package.mjs";

const PLACEHOLDER_DATABASE_ID = "00000000-0000-4000-8000-000000000000";
const VALID_DATABASE_ID = "123e4567-e89b-42d3-a456-426614174000";
const hosting = { d1: "DB" };

function binding(databaseId, name = "DB") {
  return {
    binding: name,
    database_id: arguments.length === 0 ? VALID_DATABASE_ID : databaseId,
  };
}

test("D1 package contract accepts the exact Sites placeholder or a valid nonzero UUID", () => {
  assert.equal(
    verifyD1PackageContract(hosting, [binding(PLACEHOLDER_DATABASE_ID)]).database_id,
    PLACEHOLDER_DATABASE_ID,
  );
  assert.equal(
    verifyD1PackageContract(hosting, [binding(VALID_DATABASE_ID)]).database_id,
    VALID_DATABASE_ID,
  );
});

test("D1 package contract rejects null or alternate hosting bindings", () => {
  assert.throws(
    () => verifyD1PackageContract({ d1: null }, [binding()]),
    /d1 must equal DB/,
  );
  assert.throws(
    () => verifyD1PackageContract({ d1: "DATABASE" }, [binding(VALID_DATABASE_ID, "DATABASE")]),
    /d1 must equal DB/,
  );
  assert.throws(
    () => verifyD1PackageContract(hosting, [binding(VALID_DATABASE_ID, "DATABASE")]),
    /D1 binding must equal DB/,
  );
});

test("D1 package contract rejects malformed and non-exact placeholder database IDs", () => {
  for (const databaseId of [
    undefined,
    null,
    "",
    "not-a-uuid",
    "00000000-0000-0000-0000-000000000000",
    `${PLACEHOLDER_DATABASE_ID}-extra`,
  ]) {
    assert.throws(
      () => verifyD1PackageContract(hosting, [binding(databaseId)]),
      /exact Sites placeholder or a valid nonzero UUID/,
      `database_id ${String(databaseId)} should be rejected`,
    );
  }
});

test("D1 package contract rejects duplicate expected bindings", () => {
  assert.throws(
    () => verifyD1PackageContract(hosting, [binding(), binding()]),
    /exactly one D1 binding/,
  );
});

test("D1 package contract rejects extra bindings", () => {
  assert.throws(
    () => verifyD1PackageContract(hosting, [binding(), binding(VALID_DATABASE_ID, "ANALYTICS_DB")]),
    /exactly one D1 binding/,
  );
});
