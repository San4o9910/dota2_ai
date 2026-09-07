export const STANDALONE_ORIGIN = 'https://narma-72-56-98-68.sslip.io';

// The old deployment is a redirect only. Never forward credentials, bodies,
// query strings or the ChatGPT identity to the independent server.
export function retiredSiteResponse(request) {
  const path = new URL(request.url).pathname;
  if (path.startsWith('/api/')) {
    return Response.json({ error: 'Платформа переехала на отдельный сервер.', code: 'SITE_MOVED', url: STANDALONE_ORIGIN },
      { status: 410, headers: { 'Cache-Control': 'no-store' } });
  }
  if (['GET', 'HEAD'].includes(request.method) && !path.startsWith('/_next/') && !path.startsWith('/assets/')) {
    const destination = ['/account', '/replays', '/videos'].includes(path) ? path : path === '/analyses' ? '/videos' : '/';
    return new Response(null, { status: 307, headers: { Location: STANDALONE_ORIGIN + destination, 'Cache-Control': 'no-store' } });
  }
  return null;
}
