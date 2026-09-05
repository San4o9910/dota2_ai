"use client";
import {useEffect,useRef} from "react";

/** A geographic data visualization of the actual 7.41 terrain grid.
 * Source pixels encode height/trees, not a decorative invented map. */
export default function TerrainMap({onError}:{onError:()=>void}) {
  const canvas=useRef<HTMLCanvasElement>(null);
  const errorRef=useRef(onError);
  useEffect(()=>{errorRef.current=onError;},[onError]);
  useEffect(()=>{
    let disposed=false;
    const img=new Image();
    img.onload=()=>{
      if(disposed||!canvas.current)return;
      try {
        if(img.width!==1635||img.height!==327)throw new Error("Unexpected terrain grid");
        const source=document.createElement("canvas");source.width=img.width;source.height=img.height;
        const sourceContext=source.getContext("2d",{willReadFrequently:true});if(!sourceContext)throw new Error("Canvas unavailable");
        sourceContext.drawImage(img,0,0);
        const pixels=sourceContext.getImageData(0,0,img.width,img.height).data;
        const ctx=canvas.current.getContext("2d");if(!ctx)throw new Error("Canvas unavailable");
        const output=ctx.createImageData(327,327);
        for(let row=0;row<327;row++)for(let col=0;col<327;col++){
          const i=(row*1635+col)*4;const height=pixels[i];
          const tree=(row*1635+327+col)*4;
          const hasTree=pixels[tree+1]===0 && pixels[tree+2]===0;
          const blocked=pixels[(row*1635+654+col)*4]===0;
          const radiant=row>col;
          let color:number[];
          if(height===255)color=[11,19,22];
          else if(height===0)color=[44,86,94];
          else {
            const lift=Math.min(30,height/4);
            color=radiant ? [61+lift,83+lift,58+lift*.6] : [68+lift,73+lift,77+lift];
            if(blocked)color=color.map(c=>c*.78);
            if(hasTree)color=radiant?[30+lift*.3,60+lift*.5,37+lift*.3]:[37+lift*.3,50+lift*.4,54+lift*.5];
            const north=row>0 ? pixels[((row-1)*1635+col)*4] : height;
            if(north!==255 && north<height)color=color.map(c=>c*.6);
          }
          const out=(row*327+col)*4;
          output.data[out]=color[0];output.data[out+1]=color[1];output.data[out+2]=color[2];output.data[out+3]=255;
        }
        ctx.putImageData(output,0,0);
      }catch{errorRef.current();}
    };
    img.onerror=()=>{if(!disposed)errorRef.current();};
    img.src="/maps/7.41/terrain.png";
    return()=>{disposed=true;};
  },[]);
  return <canvas ref={canvas} width={327} height={327} className="game-map terrain-map" role="img" aria-label="Рельеф, река и деревья карты Dota 2 патча 7.41"/>;
}
