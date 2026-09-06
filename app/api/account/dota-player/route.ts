import { requireApiAccount, accountApiError, accountJson } from "@/lib/auth/api-account";
import { D1PlayerBindingStore } from "@/lib/dota/player-binding";
import { ProfileBindingRequestSchema } from "@/lib/dota/player-identity";
import { bindProfileFromReplay } from "@/lib/replay/bind-profile";
import { replayBucket } from "@/lib/replay/uploads";
import { readBoundedJson } from "@/lib/security/bounded-json";
export const dynamic = "force-dynamic";
export async function GET() {
  try { const {account,db}=await requireApiAccount(undefined,true);
    return accountJson({profile:await new D1PlayerBindingStore(db).get(account.id)});
  } catch(error) { return accountApiError(error); }
}
export async function POST(request: Request) {
  try { const {account,db}=await requireApiAccount(request,true);
    const input=ProfileBindingRequestSchema.parse(await readBoundedJson(request,4096));
    if(input.replayId) return accountJson(await bindProfileFromReplay(db,replayBucket(),account.id,{...input,replayId:input.replayId}));
    const store=new D1PlayerBindingStore(db);
    const target=await store.resolve(account.id,input,{signal:request.signal});
    return accountJson({profile:await store.get(account.id),target});
  } catch(error) { return accountApiError(error); }
}
