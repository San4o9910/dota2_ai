// External scheduler for persisted jobs; run independently of the replay parser.
const origin=new URL(process.env.NARMA_SITE_ORIGIN??"");
const token=process.env.NARMA_REPLAY_WORKER_TOKEN;
if(origin.protocol!=="https:"||origin.pathname!=="/"||origin.username||origin.password||!token||token.length<32)throw new Error("WORKER_CONFIGURATION_REQUIRED");
const headers={Authorization:`Bearer ${token}`};
if(process.env.NARMA_SITES_ACCESS_TOKEN)headers["OAI-Sites-Authorization"]=`Bearer ${process.env.NARMA_SITES_ACCESS_TOKEN}`;
do {
  try{const result=await fetch(new URL("/api/analysis-worker/run-next",origin),{method:"POST",redirect:"error",headers,signal:AbortSignal.timeout(35000)});console.log(JSON.stringify({event:"analysis_poll",status:result.status}));}
  catch{console.error(JSON.stringify({event:"analysis_poll_unavailable"}));}
  if(!process.argv.includes("--once"))await new Promise(resolve=>setTimeout(resolve,10000));
}while(!process.argv.includes("--once"));
