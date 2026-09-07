// Source 2 CDemoFileInfo only. This does not parse gameplay or determine player slots.
const MAX_PACKED = 256 * 1024;
const MAX_DECODED = 1024 * 1024;
const invalid = () => new Error("Invalid Source 2 replay metadata");
type Cursor = { bytes: Uint8Array; at: number };
function uint(cursor: Cursor): bigint {
  let value = BigInt("0");
  for (let i = 0; i < 10; i++) {
    if (cursor.at >= cursor.bytes.length) throw invalid();
    const byte = cursor.bytes[cursor.at++];
    if (i === 9 && byte > 1) throw invalid();
    value |= BigInt(byte & 127) << BigInt(7 * i);
    if (!(byte & 128)) return value;
  }
  throw invalid();
}
function small(cursor: Cursor, max: number): number {
  const value = uint(cursor);
  if (value > BigInt(max)) throw invalid();
  return Number(value);
}
export function decodeSnappy(bytes: Uint8Array): Uint8Array {
  const cursor = { bytes, at: 0 };
  const output = new Uint8Array(small(cursor, MAX_DECODED));
  let written = 0;
  function little(count: number) {
    if (cursor.at + count > bytes.length) throw invalid();
    let value = 0;
    for (let i = 0; i < count; i++) value += bytes[cursor.at++] * 2 ** (8 * i);
    return value;
  }
  while (cursor.at < bytes.length) {
    const tag = bytes[cursor.at++], kind = tag & 3;
    if (kind === 0) {
      const code = tag >> 2;
      const length = code < 60 ? code + 1 : little(code - 59) + 1;
      if (cursor.at + length > bytes.length || written + length > output.length) throw invalid();
      output.set(bytes.subarray(cursor.at, cursor.at + length), written);
      cursor.at += length; written += length;
    } else {
      const length = kind === 1 ? 4 + ((tag >> 2) & 7) : 1 + (tag >> 2);
      const offset = kind === 1 ? ((tag & 224) << 3) + little(1) : little(kind === 2 ? 2 : 4);
      if (offset === 0 || offset > written || written + length > output.length) throw invalid();
      for (let i = 0; i < length; i++) { output[written] = output[written - offset]; written++; }
    }
  }
  if (written !== output.length) throw invalid();
  return output;
}
type Field = { number: number; wire: number; value: bigint | Uint8Array };
function fields(bytes: Uint8Array): Field[] {
  const cursor = { bytes, at: 0 }, result: Field[] = [];
  while (cursor.at < bytes.length) {
    if (result.length >= 4096) throw invalid();
    const key = small(cursor, 0xffffffff), wire = key & 7, number = Math.floor(key / 8);
    if (!number) throw invalid();
    if (wire === 0) result.push({ number, wire, value: uint(cursor) });
    else if (wire === 2) {
      const length = small(cursor, MAX_DECODED);
      if (cursor.at + length > bytes.length) throw invalid();
      result.push({ number, wire, value: bytes.subarray(cursor.at, cursor.at + length) });
      cursor.at += length;
    } else if (wire === 1 || wire === 5) {
      const start = cursor.at;
      cursor.at += wire === 1 ? 8 : 4;
      if (cursor.at > bytes.length) throw invalid();
      result.push({number, wire, value: bytes.subarray(start, cursor.at)});
    } else throw invalid();
  }
  return result;
}
function one(rows: Field[], number: number): bigint | Uint8Array | undefined {
  const matches = rows.filter(row => row.number === number);
  if (matches.length > 1) throw invalid();
  if (matches.length && matches[0].wire !== 0 && matches[0].wire !== 2) throw invalid();
  return matches[0]?.value;
}
function message(value: bigint | Uint8Array | undefined): Uint8Array {
  if (!(value instanceof Uint8Array)) throw invalid();
  return value;
}
function integer(value: bigint | Uint8Array | undefined, fallback?: bigint): bigint {
  if (value === undefined && fallback !== undefined) return fallback;
  if (typeof value !== "bigint") throw invalid();
  return value;
}
const utf8 = new TextDecoder("utf-8", { fatal: true });
function string(value: bigint | Uint8Array | undefined): string {
  const bytes = message(value);
  if (bytes.length > 512) throw invalid();
  const text = utf8.decode(bytes).trim();
  if (!text || text.length > 128 || /[\u0000-\u001f\u007f]/.test(text)) throw invalid();
  return text;
}
export type DemoMetadataPlayer = { nickname: string; accountId: number | null; heroName: string; side: "radiant" | "dire" };
export type DemoMetadata = { matchId: string; players: DemoMetadataPlayer[] };
export function parseDemoFileInfo(bytes: Uint8Array): DemoMetadata {
  const game = fields(message(one(fields(bytes), 4)));
  const dota = fields(message(one(game, 4)));
  const matchId = integer(one(dota, 1)).toString();
  if (!/^[1-9]\d{7,11}$/.test(matchId)) throw invalid();
  const players: DemoMetadataPlayer[] = [];
  for (const row of dota.filter(row => row.number === 4)) {
    if (row.wire !== 2) throw invalid();
    const player = fields(message(row.value));
    const fake = integer(one(player, 3), BigInt("0"));
    if (fake > BigInt("1")) throw invalid();
    if (fake === BigInt("1")) continue;
    const team = integer(one(player, 5));
    if (team !== BigInt("2") && team !== BigInt("3")) throw invalid();
    const steam = integer(one(player, 4), BigInt("0"));
    const account = steam - BigInt("76561197960265728");
    const heroName = string(one(player, 1));
    if (!/^npc_dota_hero_[a-z0-9_]+$/.test(heroName)) throw invalid();
    players.push({ nickname: string(one(player, 2)), heroName, side: team === BigInt("2") ? "radiant" : "dire",
      accountId: account > BigInt("0") && account < BigInt("4294967295") ? Number(account) : null });
  }
  if (players.length !== 10 || players.filter(p => p.side === "radiant").length !== 5) throw invalid();
  const ids = players.flatMap(p => p.accountId === null ? [] : [p.accountId]);
  if (new Set(ids).size !== ids.length) throw invalid();
  return { matchId, players };
}
export async function readDemoMetadata(size: number, readRange: (offset: number, length: number) => Promise<Uint8Array>): Promise<DemoMetadata> {
  if (!Number.isSafeInteger(size) || size < 20) throw invalid();
  async function read(offset: number, length: number) {
    if (offset < 0 || length < 1 || offset + length > size || length > MAX_PACKED) throw invalid();
    const bytes = await readRange(offset, length);
    if (bytes.length !== length) throw invalid();
    return bytes;
  }
  const header = await read(0, 16);
  if (utf8.decode(header.subarray(0, 8)) !== "PBDEMS2\0") throw invalid();
  const offset = new DataView(header.buffer, header.byteOffset, header.byteLength).getUint32(8, true);
  if (offset < 16 || offset >= size) throw invalid();
  const cursor = { bytes: await read(offset, Math.min(30, size - offset)), at: 0 };
  const command = small(cursor, 0xffffffff);
  small(cursor, 0xffffffff); // Tick is framing only, never a player ordinal.
  const length = small(cursor, MAX_PACKED);
  if (command !== 2 && command !== 66) throw invalid();
  const packed = await read(offset + cursor.at, length);
  return parseDemoFileInfo(command === 66 ? decodeSnappy(packed) : packed);
}
