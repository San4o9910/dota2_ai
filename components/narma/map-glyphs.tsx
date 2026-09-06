import type { CampTier } from "@/lib/replay/map-camps";

/** Vector minimap symbols remain sharp at browser zoom and on Retina displays. */
export function WardGlyph({kind}:{kind:"observer"|"sentry"}) {
  return <svg className="map-ward-glyph" viewBox="0 0 32 32" fill="none" aria-hidden="true" focusable="false">
    <ellipse cx="16" cy="25" rx="12" ry="3.5" fill="#020705" opacity=".8"/>
    <path d="M3 18c0-4.4 5.8-8.2 13-8.2S29 13.6 29 18v3c-1.8 4.2-6.5 6.4-13 6.4S4.8 25.2 3 21z" fill="currentColor" stroke="#07120d" strokeWidth="2" strokeLinejoin="round"/>
    <path d="M4.5 21c5.5 4.5 17.5 4.5 23 0v2c-5 5.2-18 5.2-23 0z" fill="#06120c" opacity=".4"/>
    <path d="M5 16.5C7.5 10 11 7 16 7s8.5 3 11 9.5C24 20.8 20.5 23 16 23S8 20.8 5 16.5z" fill="#07170e" stroke="currentColor" strokeWidth="2.3"/>
    {kind==="observer"
      ? <><ellipse cx="16" cy="14.5" rx="5.2" ry="5.6" fill="currentColor"/><ellipse cx="16" cy="14.4" rx="2.2" ry="3.6" fill="#041008"/></>
      : <><path d="m16 8 6 6.5-6 6.5-6-6.5z" fill="currentColor"/><path d="m16 11 2.7 3.5L16 18l-2.7-3.5z" fill="#041008"/><path d="M11 28h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></>}
    <path d="M8 15c1.2-2 2.5-3.4 4-4.4" stroke="#fff" strokeOpacity=".55" strokeWidth="1.4" strokeLinecap="round"/>
    <circle cx="18" cy="11.5" r="1.5" fill="#fff" fillOpacity=".8"/>
  </svg>;
}

export function CampGlyph({tier}:{tier:CampTier}) {
  const ancient=tier==="ancient";
  const base=tier==="large"?19:tier==="medium"?22:25;
  return <svg className="map-camp-glyph" viewBox="0 0 32 32" fill="none" aria-hidden="true" focusable="false">
    <path d={`M16 3 29 ${base}H3z`} fill="currentColor" stroke="#071015" strokeWidth="3" strokeLinejoin="round"/>
    {ancient ? <path d="m16 11 6 10H10z" fill="#081418"/> : <path d={`M16 7 22 ${base-4}H10z`} fill="#fff" fillOpacity=".65"/>}
    {(tier==="medium"||tier==="large")&&<path d={`M6 ${base+3}H26`} stroke="#071015" strokeWidth="5" strokeLinecap="round"/>}
    {(tier==="medium"||tier==="large")&&<path d={`M6 ${base+3}H26`} stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"/>}
    {tier==="large"&&<><path d="M6 28H26" stroke="#071015" strokeWidth="5" strokeLinecap="round"/><path d="M6 28H26" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"/></>}
  </svg>;
}
