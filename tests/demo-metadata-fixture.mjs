// Synthetic Source 2 metadata; never contains a user's replay or Steam identity.
export function varint(value) {
  let n=BigInt(value);const result=[];
  do {let byte=Number(n&127n);n>>=7n;if(n)byte|=128;result.push(byte);} while(n);
  return Buffer.from(result);
}
const integer=(field,value)=>Buffer.concat([varint(field*8),varint(value)]);
const bytes=(field,value)=>Buffer.concat([varint(field*8+2),varint(value.length),value]);
const string=(field,value)=>bytes(field,Buffer.from(value));
export function metadataFixture({matchId="8963624400",compressed=true,mutate=()=>{}}={}) {
  const players=Array.from({length:10},(_,i)=>({nickname:`Player_${i}`,accountId:1000+i,team:i<5?2:3}));
  mutate(players);
  const dota=Buffer.concat([integer(1,matchId),...players.map(p=>bytes(4,Buffer.concat([
    string(1,"npc_dota_hero_necrolyte"),string(2,p.nickname),integer(3,0),integer(4,p.accountId===null?0n:76561197960265728n+BigInt(p.accountId)),integer(5,p.team),
  ])))]);
  const info=bytes(4,bytes(4,dota));
  // A raw Snappy stream using one extended literal block.
  const length=info.length-1;
  const packed=compressed?Buffer.concat([varint(info.length),Buffer.from([244,length&255,length>>8]),info]):info;
  const prefix=Buffer.alloc(64);prefix.write("PBDEMS2\0");prefix.writeUInt32LE(64,8);
  const file=Buffer.concat([prefix,varint(compressed?66:2),varint(152653),varint(packed.length),packed]);
  return {file,info,players};
}
