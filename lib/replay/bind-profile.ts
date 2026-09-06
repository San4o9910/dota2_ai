import { D1PlayerBindingStore } from "@/lib/dota/player-binding";
import { playerError, selectIdentity, type PlayerMatchRequest } from "@/lib/dota/player-identity";
import { readDemoMetadata } from "@/lib/replay/demo-metadata";
import { ownedUpload } from "@/lib/replay/uploads";

export async function bindProfileFromReplay(db: D1Database, bucket: R2Bucket, userId: string, input: PlayerMatchRequest & {replayId: string}) {
  const store = new D1PlayerBindingStore(db);
  await store.takeLookupBudget(userId);
  const profile = await store.get(userId);
  if (!profile && !input.nickname) throw playerError("DOTA_PROFILE_REQUIRED", "Укажите ник из этого реплея.");
  const upload = await ownedUpload(db, userId, input.replayId);
  if (!["uploaded", "processing", "ready", "failed"].includes(upload.state) || upload.failureCode === "DELETE_PENDING")
    throw playerError("DOTA_REPLAY_NOT_UPLOADED", "Дождитесь завершения загрузки реплея.");
  if (!upload.filename.toLowerCase().endsWith(".dem"))
    throw playerError("DOTA_REPLAY_COMPRESSED", "Для привязки без OpenDota загрузите распакованный файл .dem. Файл .dem.bz2 сохранён для полного разбора.");
  const object = await bucket.head(upload.objectKey);
  if (!object || object.size !== upload.sizeBytes)
    throw playerError("DOTA_REPLAY_NOT_UPLOADED", "Файл ещё не загружен полностью. Повторите загрузку.");
  let metadata;
  try {
    metadata = await readDemoMetadata(object.size, async (offset, length) => {
      const range = await bucket.get(upload.objectKey, {range: {offset, length}, onlyIf: {etagMatches: object.etag}});
      if (!range || !("body" in range)) throw new Error("Replay changed during metadata read");
      return new Uint8Array(await range.arrayBuffer());
    });
  } catch {
    throw playerError("DOTA_REPLAY_METADATA_UNAVAILABLE", "Не удалось прочитать состав игроков из этого .dem. Файл сохранён; попробуйте другой реплей или OpenDota.");
  }
  if (metadata.matchId !== input.matchId)
    throw playerError("DOTA_REPLAY_MATCH_MISMATCH", "Match ID не совпадает с матчем внутри выбранного реплея.");
  const selected = selectIdentity(metadata.players, input.nickname, profile?.accountId);
  // Recheck ownership/state after range reads; never persist the other nine identities.
  const current = await ownedUpload(db, userId, input.replayId);
  if (current.failureCode === "DELETE_PENDING") throw playerError("DOTA_REPLAY_NOT_UPLOADED", "Реплей удаляется. Выберите другой файл.");
  const bound = await store.bindSelectedProfile(userId, selected, input.matchId);
  const target = await store.target(userId, input.matchId);
  return {profile: bound, target, status: target ? "ready" : "awaiting_replay_parse"};
}
