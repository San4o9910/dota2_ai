"use client";
/* eslint-disable @next/next/no-img-element */
/** Original server-provided game raster, with no generated or recolored terrain. */
export default function GameMapImage({onError}:{onError:()=>void}) {
  return <img src="/maps/7.41/game-map.jpg" width={2166} height={2048}
    className="game-map original-game-map" alt="Игровая карта Dota 2, патч 7.41"
    draggable={false} decoding="async" onError={onError}/>;
}
