import { requireApiAccount, accountApiError, accountJson } from "@/lib/auth/api-account";
import { D1PlayerBindingStore } from "@/lib/dota/player-binding";
import { PlayerMatchRequestSchema } from "@/lib/dota/player-identity";
import { readBoundedJson } from "@/lib/security/bounded-json";
export const dynamic = "force-dynamic";
export async function GET() {
  try { const {account,db}=await requireApiAccount(undefined,true);
    return accountJson({profile:await new D1PlayerBindingStore(db).get(account.id)});
  } catch(error) { return accountApiError(error); }
}
export async function POST(request: Request) {
  try { const {account,db}=await requireApiAccount(request,true);
    const input=PlayerMatchRequestSchema.parse(await readBoundedJson(request,4096));
    const store=new D1PlayerBindingStore(db);
    const target=await store.resolve(account.id,input,{signal:request.signal});
    return accountJson({profile:await store.get(account.id),target});
  } catch(error) { return accountApiError(error); }
}
