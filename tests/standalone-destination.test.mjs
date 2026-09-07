import test from 'node:test';
import assert from 'node:assert/strict';
import { retiredSiteResponse, STANDALONE_ORIGIN } from '../config/standalone-destination.mjs';

test('old pages go to independent portal without sharing identity or URL secrets', () => {
  const response = retiredSiteResponse(new Request('https://old.example/analyses?token=private', { headers: { 'oai-authenticated-user-id': 'private-owner' } }));
  assert.equal(response.status, 307);
  assert.equal(response.headers.get('Location'), STANDALONE_ORIGIN + '/videos');
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
});
test('old APIs are retired instead of forwarding user data or calling a provider', async () => {
  for (const path of ['/api/scan', '/api/matches/8984479726', '/api/videos', '/api/account/dota-player']) {
    const response = retiredSiteResponse(new Request('https://old.example'+path, { method: 'POST', body: 'private' }));
    assert.equal(response.status, 410);
    assert.equal((await response.json()).code, 'SITE_MOVED');
    assert.equal(response.headers.get('Location'), null);
  }
});
