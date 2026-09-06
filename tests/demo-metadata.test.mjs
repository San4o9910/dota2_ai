import assert from "node:assert/strict";
import test,{after} from "node:test";
import {createAnalysisVite} from "./analysis-test-helpers.mjs";
import {metadataFixture,varint} from "./demo-metadata-fixture.mjs";
const vite=await createAnalysisVite();after(()=>vite.close());
const {readDemoMetadata,decodeSnappy,parseDemoFileInfo}=await vite.ssrLoadModule("/lib/replay/demo-metadata.ts");
const read=file=>readDemoMetadata(file.length,async(offset,length)=>file.subarray(offset,offset+length));
test("compressed and uncompressed footer use bounded ranges and preserve Steam64 precision without inventing slots",async()=>{
  for(const compressed of [true,false]){
    const {file}=metadataFixture({compressed,mutate:players=>{players[0].accountId=3000000001;players[0].nickname="Игрок";}});
    const ranges=[];
    const metadata=await readDemoMetadata(file.length,async(offset,length)=>{ranges.push({offset,length});return file.subarray(offset,offset+length);});
    assert.equal(metadata.matchId,"8963624400");assert.equal(metadata.players[0].accountId,3000000001);
    assert.equal(metadata.players[0].nickname,"Игрок");assert.equal(metadata.players[5].side,"dire");
    assert.ok(metadata.players.every(p=>!("playerSlot" in p)));
    assert.equal(ranges.length,3);assert.equal(ranges[0].length,16);assert.ok(ranges.every(r=>r.length<1024));
  }
});
test("Snappy overlap and all copy encodings decode; invalid copies and size bombs fail",()=>{
  for(const [hex,expected] of [["0908414243160300","ABCABCABC"],["0500410101","AAAAA"],["0500410f01000000","AAAAA"]])
    assert.equal(Buffer.from(decodeSnappy(Buffer.from(hex,"hex"))).toString(),expected);
  for(const hex of ["0500410100","0500410102","05004101","020041","0108414243","000041"])
    assert.throws(()=>decodeSnappy(Buffer.from(hex,"hex")));
  assert.throws(()=>decodeSnappy(varint(1024*1024+1)));
});
test("bad headers, footer commands, truncated frames and excessive lengths never trigger an unbounded read",async()=>{
  const {file}=metadataFixture();
  for(const mutate of [b=>b.fill(0,0,8),b=>b.writeUInt32LE(0,8),b=>b.writeUInt32LE(b.length+1,8),b=>{b[64]=3;}]){
    const bad=Buffer.from(file);mutate(bad);await assert.rejects(read(bad));
  }
  await assert.rejects(read(file.subarray(0,file.length-1)));
  await assert.rejects(readDemoMetadata(file.length,async()=>new Uint8Array(0)));
  const prefix=Buffer.from(file.subarray(0,64));
  await assert.rejects(read(Buffer.concat([prefix,varint(2),varint(10),varint(262145)])));
});
test("duplicate accounts, missing teams, malformed UTF8 and duplicate singular fields are rejected",()=>{
  for(const mutate of [p=>{p[1].accountId=p[0].accountId;},p=>{p[0].team=3;},p=>{p[0].nickname="\u0000";}])
    assert.throws(()=>parseDemoFileInfo(metadataFixture({mutate}).info));
  const info=Buffer.from(metadataFixture().info);const at=info.indexOf(Buffer.from("Player_0"));info[at]=255;
  assert.throws(()=>parseDemoFileInfo(info));
  const valid=metadataFixture().info;
  assert.throws(()=>parseDemoFileInfo(Buffer.concat([valid,valid])));
  // Field 4 repeated with fixed32 wire type must not evade singular validation.
  assert.throws(()=>parseDemoFileInfo(Buffer.concat([valid,Buffer.from([37,0,0,0,0])])));
});
