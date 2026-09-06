import { fetchOpenDotaMatch, type AnalysisFetch } from "@/lib/analysis/opendota";
import { normalizeOpenDotaMatch } from "@/lib/analysis/normalizer";
import { D1ScanMatchCache, D1FixedWindowRateLimiter } from "@/lib/scan/storage";
import {canonicalSha256} from "@/lib/analysis/canonical-json";
import { IdentityRosterSchema, extractIdentityRoster, selectIdentity, playerError, type PlayerMatchRequest, type PlayerTarget } from "@/lib/dota/player-identity";

export type DotaProfile = { accountId: number; nickname: string; sourceMatchId: string; linkedAt: string };
export class D1PlayerBindingStore {
  constructor(private db: D1Database) {}
  get(userId: string) {
    return this.db.prepare("SELECT account_id AS accountId,nickname,source_match_id AS sourceMatchId,created_at AS linkedAt FROM dota_player_profiles WHERE user_id=?1")
      .bind(userId).first<DotaProfile>();
  }
  target(userId: string, matchId: string) {
    return this.db.prepare(`SELECT t.match_id AS matchId,t.account_id AS accountId,t.player_slot AS playerSlot,t.hero_id AS heroId,p.nickname
      FROM dota_match_targets t JOIN dota_player_profiles p ON p.user_id=t.user_id AND p.account_id=t.account_id
      WHERE t.user_id=?1 AND t.match_id=?2`).bind(userId,matchId).first<PlayerTarget>();
  }
  async assertTarget(userId: string, matchId: string, playerSlot: number) {
    const target = await this.target(userId,matchId);
    if (!target || target.playerSlot !== playerSlot) throw playerError("DOTA_TARGET_MISMATCH", "Разбор доступен только для закреплённого игрока.", 403);
    return target;
  }
  async resolve(userId: string, input: PlayerMatchRequest, options: { fetch?: AnalysisFetch; signal?: AbortSignal } = {}) {
    const profile = await this.get(userId);
    if (profile) {
      const known = await this.target(userId,input.matchId);
      if (known) return known;
    } else if (!input.nickname) throw playerError("DOTA_PROFILE_REQUIRED", "Укажите свой ник и закрепите профиль Dota.", 409);

    const limit=await new D1FixedWindowRateLimiter(this.db).take(await canonicalSha256({scope:"dota-profile",userId}),Date.now());
    if(!limit.allowed) throw playerError("DOTA_LOOKUP_RATE_LIMITED","Слишком много запросов поиска игрока. Попробуйте позже.",429);

    // Private replay identities never enter the shared match cache or model input.
    const replay = await this.db.prepare("SELECT identity_payload AS identities FROM replay_uploads WHERE user_id=?1 AND match_id=?2 AND state='ready' AND identity_payload IS NOT NULL ORDER BY updated_at DESC LIMIT 1")
      .bind(userId,input.matchId).first<{identities:string}>();
    let roster;
    if (replay) roster = IdentityRosterSchema.parse(JSON.parse(replay.identities));
    else {
      const raw = await fetchOpenDotaMatch(input.matchId,options);
      roster = extractIdentityRoster(raw.players);
      await new D1ScanMatchCache(this.db).put(normalizeOpenDotaMatch(raw));
    }
    const selected = selectIdentity(roster,input.nickname,profile?.accountId);
    const nickname = selected.nickname?.trim() || profile?.nickname || input.nickname!;
    await this.db.prepare(`INSERT INTO dota_player_profiles(user_id,account_id,nickname,source_match_id)
      VALUES (?1,?2,?3,?4) ON CONFLICT(user_id) DO NOTHING`).bind(userId,selected.accountId,nickname,input.matchId).run();
    const bound = await this.get(userId);
    if (!bound || bound.accountId !== selected.accountId)
      throw playerError("DOTA_PROFILE_LOCKED", "В этом аккаунте уже закреплён другой игрок. Профиль не изменён.");
    await this.db.prepare(`INSERT INTO dota_match_targets(user_id,match_id,account_id,player_slot,hero_id)
      SELECT ?1,?2,?3,?4,?5 WHERE EXISTS(SELECT 1 FROM dota_player_profiles WHERE user_id=?1 AND account_id=?3)
      ON CONFLICT(user_id,match_id) DO NOTHING`).bind(userId,input.matchId,selected.accountId,selected.playerSlot,selected.heroId).run();
    const target = await this.assertTarget(userId,input.matchId,selected.playerSlot);
    if (target.accountId !== selected.accountId || target.heroId !== selected.heroId)
      throw playerError("DOTA_TARGET_MISMATCH", "Данные игрока не совпали с сохранённым матчем.");
    return target;
  }
}
