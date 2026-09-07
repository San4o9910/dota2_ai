/** Run on a private machine next to the pinned odota/parser container.
 * Requires Node22+, bzip2, NARMA_SITE_ORIGIN and NARMA_REPLAY_WORKER_TOKEN.
 * Never expose the upstream parser or its arbitrary replay_url endpoint. */
import {createReadStream,createWriteStream} from "node:fs";
import {mkdtemp,rm,stat} from "node:fs/promises";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {Readable,Transform} from "node:stream";
import {pipeline} from "node:stream/promises";

import {spawn} from "node:child_process";
import {createReplayMetadata,acceptReplayEvent,assembleReplayMatch} from "./replay-adapter.mjs";

const origin=new URL(process.env.NARMA_SITE_ORIGIN??"");
if(origin.protocol!=="https:"||origin.username||origin.password||origin.pathname!=="/")throw new Error("NARMA_SITE_ORIGIN must be an HTTPS origin");
const token=process.env.NARMA_REPLAY_WORKER_TOKEN;
if(!token||token.length<32)throw new Error("NARMA_REPLAY_WORKER_TOKEN is required");
const headers={Authorization:`Bearer ${token}`};
if(process.env.NARMA_SITES_ACCESS_TOKEN)headers["OAI-Sites-Authorization"]=`Bearer ${process.env.NARMA_SITES_ACCESS_TOKEN}`;
const MAX_UNCOMPRESSED=2*1024*1024*1024;
const bounded=limit=>{let n=0;return new Transform({transform(chunk,_encoding,callback){n+=chunk.length;callback(n>limit?new Error("REPLAY_TOO_LARGE"):null,chunk);}});};
async function api(path,options={}){const r=await fetch(new URL(path,origin),{...options,redirect:"error",headers:{...headers,...options.headers},signal:AbortSignal.timeout(60000)});if(!r.ok)throw new Error(`SITE_${r.status}`);return r;}
async function parse(path,blob){const size=(await stat(path)).size;const r=await fetch(`http://127.0.0.1:5600/${blob?"?blob":""}`,{method:"POST",duplex:"half",headers:{"Content-Type":"application/octet-stream","Content-Length":String(size)},body:createReadStream(path),signal:AbortSignal.timeout(300000)});if(!r.ok||!r.body)throw new Error("PARSER_UNAVAILABLE");return r;}
async function processJob(job){
  const temporary=await mkdtemp(join(tmpdir(),"narma-replay-"));const lease={"x-replay-lease":job.leaseToken};
  try{
    const input=join(temporary,"source");const response=await api(`/api/replay-worker/${job.id}`,{headers:lease});
    await pipeline(Readable.fromWeb(response.body),bounded(job.sizeBytes),createWriteStream(input));
    if((await stat(input)).size!==job.sizeBytes)throw new Error("SOURCE_TRUNCATED");
    let dem=input;
    if(job.filename.endsWith(".bz2")){
      dem=join(temporary,"replay.dem");const child=spawn("bzip2",["-dc",input],{stdio:["ignore","pipe","ignore"]});
      const completed=new Promise((resolve,reject)=>{child.once("error",reject);child.once("exit",code=>code===0?resolve():reject(new Error("BZIP2_FAILED")));});
      const deadline=setTimeout(()=>child.kill("SIGKILL"),60000);
      try{await Promise.all([pipeline(child.stdout,bounded(MAX_UNCOMPRESSED),createWriteStream(dem)),completed]);}finally{clearTimeout(deadline);child.kill();}
    }
    const events=await parse(dem,false);const metadata=createReplayMetadata();
    let pending=Buffer.alloc(0), eventBytes=0;
    for await(const chunk of Readable.fromWeb(events.body)) {
      eventBytes+=chunk.length;if(eventBytes>MAX_UNCOMPRESSED)throw new Error("PARSER_RESULT_TOO_LARGE");
      pending=Buffer.concat([pending,chunk]);let newline;
      while((newline=pending.indexOf(10))!==-1) {
        if(newline>2*1024*1024)throw new Error("PARSER_LINE_TOO_LARGE");
        const line=pending.subarray(0,newline).toString("utf8");pending=pending.subarray(newline+1);
        if(line.trim())acceptReplayEvent(metadata,JSON.parse(line));
      }
      if(pending.length>2*1024*1024)throw new Error("PARSER_LINE_TOO_LARGE");
    }
    if(pending.length)acceptReplayEvent(metadata,JSON.parse(pending.toString("utf8")));
    const compiled=await parse(dem,true);const chunks=[];let bytes=0;
    for await(const chunk of Readable.fromWeb(compiled.body)){bytes+=chunk.length;if(bytes>8*1024*1024)throw new Error("PARSER_RESULT_TOO_LARGE");chunks.push(chunk);}
    const match=assembleReplayMatch(metadata,JSON.parse(Buffer.concat(chunks).toString("utf8")));
    // Patch and timestamps come only from the uploaded replay.
    await api(`/api/replay-worker/${job.id}`,{method:"POST",headers:{...lease,"Content-Type":"application/json"},body:JSON.stringify({match})});
    console.log(JSON.stringify({event:"replay_ready",id:job.id,matchId:match.match_id}));
  }catch(error){console.error(JSON.stringify({event:"replay_failed",id:job.id,code:error instanceof Error?error.message.slice(0,80):"FAILED"}));if(error instanceof Error && /^(REPLAY_(INCOMPLETE|PLAYERS_INCOMPLETE|SLOTS_INCOMPLETE|HERO_CHANGED|EPILOGUE_INVALID|TOO_LARGE)|BZIP2_FAILED|SITE_4(00|13|15))$/.test(error.message))await api(`/api/replay-worker/${job.id}`,{method:"DELETE",headers:lease}).catch(()=>{});
    // A transport failure has an unknown outcome. Let the lease expire and retry.
}
  finally{await rm(temporary,{recursive:true,force:true});}
}
let claimKey=crypto.randomUUID();
do{
  try {
  const {job}=await(await api("/api/replay-worker/claim",{method:"POST",headers:{"Idempotency-Key":claimKey}})).json();
  claimKey=crypto.randomUUID();
  if(job)await processJob(job);else if(!process.argv.includes("--once"))await new Promise(r=>setTimeout(r,10000));
  }catch {console.error(JSON.stringify({event:"replay_claim_unavailable"}));if(!process.argv.includes("--once"))await new Promise(r=>setTimeout(r,10000));}
}while(!process.argv.includes("--once"));
