import assert from 'node:assert/strict';
import test,{after} from 'node:test';
import {createServer} from 'vite';
import {analysisRoot} from './analysis-test-helpers.mjs';

globalThis.__videoTestEnv={VIDEO_SERVICE_ORIGIN:'https://video.example.test',VIDEO_SERVICE_TOKEN:'test-'+'x'.repeat(40)};
const originalFetch=globalThis.fetch;
const vite=await createServer({appType:'custom',configFile:false,root:analysisRoot,server:{middlewareMode:true},plugins:[{
  name:'video-boundary-stubs',
  resolveId(id){if(id==='cloudflare:workers')return '\0video-env';if(id==='@/lib/auth/api-account')return '\0video-account';},
  load(id){if(id==='\0video-env')return 'export const env=globalThis.__videoTestEnv;';if(id==='\0video-account')return 'export class AccountApiError extends Error {constructor(message,status){super(message);this.status=status;}}';}
}]});
after(async()=>{globalThis.fetch=originalFetch;delete globalThis.__videoTestEnv;await vite.close();});
const service=await vite.ssrLoadModule('/lib/video/service.ts');
test('video bridge sends server credentials and owner only to configured HTTPS origin',async()=>{
  let sent;globalThis.fetch=async(url,options)=>{sent={url:String(url),...options};return Response.json({videos:[]});};
  await service.videoService('owner-1','/v1/videos');
  assert.equal(sent.url,'https://video.example.test/v1/videos');
  assert.equal(sent.headers['X-Narma-Owner'],'owner-1');
  assert.equal(sent.redirect,'error');
  for(const bad of ['http://video.example.test','https://user:pass@video.example.test','https://video.example.test/path']){
    globalThis.__videoTestEnv.VIDEO_SERVICE_ORIGIN=bad;
    await assert.rejects(service.videoService('owner-1','/v1/videos'),error=>error.status===503);
  }
  globalThis.__videoTestEnv.VIDEO_SERVICE_ORIGIN='https://video.example.test';
});
test('video response is bounded while streaming and never exposes HTML errors',async()=>{
  let cancelled=false;
  const oversized=new Response(new ReadableStream({pull(controller){controller.enqueue(new Uint8Array(1024*1024));},cancel(){cancelled=true;}}));
  await assert.rejects(service.videoJsonResponse(oversized),error=>error.status===503);
  assert.equal(cancelled,true);
  await assert.rejects(service.videoJsonResponse(new Response('<html>private upstream trace</html>',{status:500})),error=>!error.message.includes('private'));
  const good=await service.videoJsonResponse(Response.json({videos:[]}));
  assert.equal(good.headers.get('Cache-Control'),'no-store');
});
test('upload bridge rejects an oversized part before forwarding',async()=>{
  const exact=new Uint8Array(5*1024*1024);exact[0]=42;
  assert.equal((await service.videoPart(new Request('https://narma.test',{method:'PUT',body:exact})))[0],42);
  await assert.rejects(service.videoPart(new Request('https://narma.test',{method:'PUT',body:new Uint8Array(exact.length+1)})),error=>error.status===413);
});
