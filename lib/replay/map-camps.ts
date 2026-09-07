// Pinned 7.41 neutral spawners from leamare/dota-interactive-map.
// Source commit f3b4d42caab7fd2de0606ff8ed6088735a63cde1; ISC notice in public/maps/7.41/LICENSE.txt.
// Side describes map geography, not ownership or current creep availability.
export type CampTier = "small" | "medium" | "large" | "ancient";
export type MapCamp = {id:string;x:number;y:number;side:"radiant"|"dire";tier:CampTier};
export const CAMP_LABELS: Record<CampTier,string> = {small:"Малый лагерь",medium:"Средний лагерь",large:"Большой лагерь",ancient:"Древние крипы"};
export const MAP_CAMPS: MapCamp[] = [
  {
    "id": "neutralcamp_evil_6",
    "x": -852,
    "y": 4940,
    "side": "dire",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_evil_9",
    "x": 3392,
    "y": -1408,
    "side": "dire",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_good_1",
    "x": 3978,
    "y": -5027,
    "side": "radiant",
    "tier": "small"
  },
  {
    "id": "neutralcamp_evil_7",
    "x": 7928,
    "y": -120,
    "side": "dire",
    "tier": "large"
  },
  {
    "id": "neutralcamp_evil_1",
    "x": -4824,
    "y": 3915,
    "side": "dire",
    "tier": "large"
  },
  {
    "id": "neutralcamp_good_2",
    "x": 4649,
    "y": -3699,
    "side": "radiant",
    "tier": "large"
  },
  {
    "id": "neutralcamp_good_5",
    "x": -1454,
    "y": -3356,
    "side": "radiant",
    "tier": "large"
  },
  {
    "id": "neutralcamp_good_4",
    "x": 186,
    "y": -5197,
    "side": "radiant",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_good_8",
    "x": -5015,
    "y": -96,
    "side": "radiant",
    "tier": "ancient"
  },
  {
    "id": "neutralcamp_evil_8",
    "x": 4352,
    "y": 48,
    "side": "dire",
    "tier": "ancient"
  },
  {
    "id": "neutralcamp_good_9",
    "x": -1983,
    "y": -4815,
    "side": "radiant",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_evil_4",
    "x": 1224,
    "y": 4176,
    "side": "dire",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_good_7",
    "x": -4013,
    "y": 992,
    "side": "radiant",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_good_11",
    "x": -720,
    "y": -7696,
    "side": "radiant",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_evil_14",
    "x": 336,
    "y": 7696,
    "side": "dire",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_evil_5",
    "x": 1064,
    "y": 2580,
    "side": "dire",
    "tier": "large"
  },
  {
    "id": "neutralcamp_evil_13",
    "x": 8430,
    "y": 1263,
    "side": "dire",
    "tier": "small"
  },
  {
    "id": "neutralcamp_good_13",
    "x": -8313,
    "y": -553,
    "side": "radiant",
    "tier": "large"
  },
  {
    "id": "neutralcamp_evil_11",
    "x": -2880,
    "y": 7376,
    "side": "dire",
    "tier": "small"
  },
  {
    "id": "neutralcamp_evil_15",
    "x": -2596,
    "y": 3850,
    "side": "dire",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_good_14",
    "x": 2768,
    "y": -8336,
    "side": "radiant",
    "tier": "small"
  },
  {
    "id": "neutralcamp_good_15",
    "x": 1922,
    "y": -3975,
    "side": "radiant",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_evil_2",
    "x": -3911,
    "y": 4829,
    "side": "dire",
    "tier": "small"
  },
  {
    "id": "neutralcamp_good_16",
    "x": -8023,
    "y": -1838,
    "side": "radiant",
    "tier": "small"
  },
  {
    "id": "neutralcamp_evil_12",
    "x": 2016,
    "y": 7896,
    "side": "dire",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_good_12",
    "x": -2415,
    "y": -8402,
    "side": "radiant",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_good_20",
    "x": 4416,
    "y": -8432,
    "side": "radiant",
    "tier": "medium"
  },
  {
    "id": "neutralcamp_evil_20",
    "x": -4208,
    "y": 8336,
    "side": "dire",
    "tier": "medium"
  }
];
