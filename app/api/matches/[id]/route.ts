import {D1AnalysisStore} from "@/lib/analyses/store";
import {AnalysisError} from "@/lib/analysis/errors";
import {accountApiError,accountJson,requireApiAccount,AccountApiError} from "@/lib/auth/api-account";
import {D1ScanMatchCache,D1FixedWindowRateLimiter} from "@/lib/scan/storage";
import {parseMatchId,fetchOpenDotaMatch} from "@/lib/analysis/opendota";
import {normalizeOpenDotaMatch} from "@/lib/analysis/normalizer";
import {canonicalSha256} from "@/lib/analysis/canonical-json";
export const dynamic="force-dynamic";
export async function GET(_request:Request,context:{params:Promise<{id:string}>}) {
  try {
    const {account,db}=await requireApiAccount();
    const {id}=await context.params;const matchId=parseMatchId(id);
    const limit=await new D1FixedWindowRateLimiter(db).take(await canonicalSha256({scope:"match_preview",account:account.id}),Date.now());
    if(!limit.allowed) throw new AccountApiError("Слишком много запросов. Повторите через несколько минут.",429);
    const cache=new D1ScanMatchCache(db);
    let match=await new D1AnalysisStore(db).getReadyReplay(account.id,matchId) ?? await cache.get(matchId);
    if(!match){match=normalizeOpenDotaMatch(await fetchOpenDotaMatch(matchId));await cache.put(match);}
    return accountJson({match});
  }catch(error){if(error instanceof AnalysisError)return accountJson({error:error.message},error.httpStatus);return accountApiError(error);}
}
