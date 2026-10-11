import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { createPlaylistShareStore, renderM3u, resolvePublicBaseUrl } from './m3uShares.js';

test('share links persist, expire, and can be revoked', async (t) => {
    const directory = await mkdtemp(path.join(os.tmpdir(), 'hfvideo-m3u-'));
    t.after(() => rm(directory, { recursive: true, force: true }));
    const filePath = path.join(directory, 'shares.json');
    const now = new Date('2026-10-03T09:00:00.000Z');
    const firstStore = createPlaylistShareStore(filePath);
    const created = await firstStore.create({
        videos: [{ id: 'film-1', title: 'Example Film', duration: 3600 }],
        expiresInDays: 1,
        now
    });

    assert.equal(created.videoCount, 1);
    assert.match(created.token, /^[\w-]{40,}$/);
    assert.match(created.accessCode, /^[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}$/);
    assert.equal((await firstStore.findActiveByToken(created.token, now)).videos[0].id, 'film-1');
    const savedRecords = await readFile(filePath, 'utf8');
    assert.equal(savedRecords.includes(created.token), false);
    assert.equal(savedRecords.includes(created.accessCode.replaceAll('-', '')), false);

    const restartedStore = createPlaylistShareStore(filePath);
    assert.equal((await restartedStore.list(now))[0].status, 'active');
    assert.equal((await restartedStore.list(now))[0].tokenHash, undefined);
    assert.equal((await restartedStore.list(now))[0].accessCodeHash, undefined);
    assert.equal((await restartedStore.findByAccessCode(created.accessCode.toLowerCase(), now)).status, 'active');
    assert.equal((await restartedStore.findByAccessCode(created.accessCode, new Date(created.expiresAt))).status, 'expired');
    assert.equal((await restartedStore.findByAccessCode('not-a-code', now)).status, 'invalid');
    assert.equal(await restartedStore.findActiveByToken(created.token, new Date(created.expiresAt)), null);
    assert.equal(await restartedStore.revoke(created.id, now), true);
    assert.equal(await restartedStore.findActiveByToken(created.token, now), null);
    assert.equal((await restartedStore.findByAccessCode(created.accessCode, now)).status, 'revoked');
    assert.equal((await restartedStore.list(now))[0].status, 'revoked');
});

test('M3U output includes compatible video entries and sanitizes line breaks', () => {
    const output = renderM3u({
        videos: [{
            id: 'film-1',
            title: 'A Film\r\n#EXT-X-KEY:bad',
            duration: 125,
            category: 'Films',
            isSeries: false
        }]
    }, 'https://stream.example');

    assert.match(output, /^#EXTM3U\r\n/);
    assert.match(output, /#EXTINF:125 tvg-id="film-1" tvg-name="A Film #EXT-X-KEY:bad" group-title="Films",A Film #EXT-X-KEY:bad/);
    assert.match(output, /https:\/\/stream\.example\/video\/film-1\r\n$/);
    assert.equal(output.includes('\r\n#EXT-X-KEY:bad\r\n'), false);
});

test('M3U output does not include catalog image URLs', () => {
    const output = renderM3u({
        videos: [{
            id: 'film-1',
            title: 'Example',
            duration: 60,
            category: 'Films',
            logo: 'http://192.168.1.20/poster.jpg'
        }]
    }, 'https://stream.example');

    assert.equal(output.includes('192.168.1.20'), false);
    assert.equal(output.includes('tvg-logo'), false);
});

test('public share URLs require an explicitly configured HTTPS hostname in production', () => {
    assert.equal(
        resolvePublicBaseUrl('', 'http://localhost:3000'),
        'http://localhost:3000'
    );
    assert.equal(
        resolvePublicBaseUrl('', 'https://request.example.com'),
        null
    );
    assert.equal(
        resolvePublicBaseUrl('https://watch.example.com/', 'http://10.0.0.4:3000'),
        'https://watch.example.com'
    );
    assert.equal(
        resolvePublicBaseUrl('"https://watch.example.com/"', 'http://10.0.0.4:3000'),
        'https://watch.example.com'
    );
    assert.equal(
        resolvePublicBaseUrl('PUBLIC_BASE_URL=https://watch.example.com', 'http://10.0.0.4:3000'),
        'https://watch.example.com'
    );
    assert.equal(
        resolvePublicBaseUrl('not a URL', 'http://10.0.0.4:3000', 'https://eshansayhan-hotlink.hf.space'),
        'https://eshansayhan-hotlink.hf.space'
    );
    assert.equal(
        resolvePublicBaseUrl('', 'https://request.example.com', 'https://eshansayhan-hotlink.hf.space'),
        'https://eshansayhan-hotlink.hf.space'
    );
    assert.throws(
        () => resolvePublicBaseUrl('http://198.51.100.8', ''),
        /must use HTTPS/
    );
});
