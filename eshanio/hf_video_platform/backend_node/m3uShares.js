import { createHash, randomBytes, randomUUID } from 'crypto';
import { mkdir, readFile, rename, unlink, writeFile } from 'fs/promises';
import path from 'path';

const STORE_VERSION = 1;

function tokenDigest(token) {
    return createHash('sha256').update(token).digest('hex');
}

function normalizeAccessCode(code) {
    return String(code ?? '').replace(/[\s-]/g, '').toUpperCase();
}

function cleanText(value, fallback = '') {
    const text = String(value ?? fallback).replace(/[\r\n]+/g, ' ').trim();
    return text || fallback;
}

function snapshotVideo(video) {
    const id = cleanText(video.id);
    const title = cleanText(video.title || video.name, 'Video');
    const isSeries = Boolean(video.is_series || video.content_type === 'dizi' || video.type === 'Dizi');

    return {
        id,
        title,
        duration: Number.isFinite(Number(video.duration)) && Number(video.duration) > 0
            ? Math.floor(Number(video.duration))
            : -1,
        category: cleanText(video.category, isSeries ? 'Diziler' : 'Filmler'),
        isSeries,
        seriesTitle: cleanText(video.series_title),
        season: Number.isInteger(Number(video.season)) ? Number(video.season) : 0,
        episode: Number.isInteger(Number(video.episode)) ? Number(video.episode) : 0,
        episodeTitle: cleanText(video.episode_title)
    };
}

function readShareStore(filePath) {
    return readFile(filePath, 'utf8')
        .then((contents) => {
            const store = JSON.parse(contents);
            if (store.version !== STORE_VERSION || !Array.isArray(store.shares)) {
                throw new Error('M3U share store has an unsupported format.');
            }
            return store;
        })
        .catch((error) => {
            if (error.code === 'ENOENT') {
                return { version: STORE_VERSION, shares: [] };
            }
            throw error;
        });
}

async function writeShareStore(filePath, store) {
    const directory = path.dirname(filePath);
    const temporaryPath = `${filePath}.${randomUUID()}.tmp`;
    await mkdir(directory, { recursive: true });
    try {
        await writeFile(temporaryPath, JSON.stringify(store, null, 2), { encoding: 'utf8', flag: 'wx' });
        await rename(temporaryPath, filePath);
    } finally {
        try {
            await unlink(temporaryPath);
        } catch (error) {
            if (error.code !== 'ENOENT') {
                throw error;
            }
        }
    }
}

export function createPlaylistShareStore(filePath) {
    let writeQueue = Promise.resolve();

    function mutate(mutator) {
        const operation = writeQueue.then(async () => {
            const store = await readShareStore(filePath);
            const result = mutator(store);
            await writeShareStore(filePath, store);
            return result;
        });
        writeQueue = operation.catch(() => {});
        return operation;
    }

    async function read() {
        await writeQueue;
        return readShareStore(filePath);
    }

    return {
        async create({ videos, expiresInDays, now = new Date() }) {
            const token = randomBytes(32).toString('base64url');
            const createdAt = now.toISOString();
            const expiresAt = new Date(now.getTime() + expiresInDays * 24 * 60 * 60 * 1000).toISOString();
            const share = {
                id: randomUUID(),
                tokenHash: tokenDigest(token),
                accessCodeHash: '',
                createdAt,
                expiresAt,
                revokedAt: null,
                videos: videos.map(snapshotVideo)
            };

            let accessCode;
            await mutate((store) => {
                do {
                    accessCode = randomBytes(6).toString('hex').toUpperCase();
                } while (store.shares.some((item) => item.accessCodeHash === tokenDigest(accessCode)));
                share.accessCodeHash = tokenDigest(accessCode);
                store.shares.push(share);
            });
            return {
                id: share.id,
                token,
                accessCode: accessCode.match(/.{1,4}/g).join('-'),
                createdAt,
                expiresAt,
                videoCount: share.videos.length
            };
        },

        async list(now = new Date()) {
            const store = await read();
            return store.shares.map(({ tokenHash, accessCodeHash, videos, ...share }) => ({
                ...share,
                videoCount: videos.length,
                status: share.revokedAt
                    ? 'revoked'
                    : new Date(share.expiresAt).getTime() <= now.getTime()
                        ? 'expired'
                        : 'active'
            }));
        },

        async findActiveByToken(token, now = new Date()) {
            const digest = tokenDigest(token);
            const store = await read();
            const share = store.shares.find((item) => item.tokenHash === digest);
            if (!share || share.revokedAt || new Date(share.expiresAt).getTime() <= now.getTime()) {
                return null;
            }
            return { ...share };
        },

        async findByAccessCode(code, now = new Date()) {
            const normalizedCode = normalizeAccessCode(code);
            if (!/^[A-F0-9]{12}$/.test(normalizedCode)) {
                return { status: 'invalid' };
            }

            const digest = tokenDigest(normalizedCode);
            const store = await read();
            const share = store.shares.find((item) => item.accessCodeHash === digest);
            if (!share) {
                return { status: 'invalid' };
            }
            if (share.revokedAt) {
                return { status: 'revoked' };
            }
            if (new Date(share.expiresAt).getTime() <= now.getTime()) {
                return { status: 'expired' };
            }
            return { status: 'active', share: { ...share } };
        },

        async revoke(id, now = new Date()) {
            return mutate((store) => {
                const share = store.shares.find((item) => item.id === id);
                if (!share) {
                    return false;
                }
                if (!share.revokedAt) {
                    share.revokedAt = now.toISOString();
                }
                return true;
            });
        }
    };
}

export function renderM3u(share, baseUrl) {
    const lines = ['#EXTM3U'];

    for (const video of share.videos) {
        const title = video.isSeries
            ? `${video.seriesTitle || video.title} S${String(video.season).padStart(2, '0')}E${String(video.episode).padStart(2, '0')}${video.episodeTitle ? ` - ${video.episodeTitle}` : ''}`
            : video.title;
        const safeTitle = cleanText(title, 'Video');

        lines.push(
            `#EXTINF:${video.duration} tvg-id="${cleanText(video.id).replace(/["\\]/g, '')}" tvg-name="${cleanText(safeTitle).replace(/["\\]/g, '')}" group-title="${cleanText(video.category).replace(/["\\]/g, '')}",${safeTitle}`,
            `${baseUrl}/video/${encodeURIComponent(video.id)}`
        );
    }

    return `${lines.join('\r\n')}\r\n`;
}

export function resolvePublicBaseUrl(configuredBaseUrl, requestBaseUrl, fallbackBaseUrl = '') {
    let configured = String(configuredBaseUrl || '').trim();
    configured = configured.replace(/^PUBLIC_BASE_URL\s*=\s*/i, '').trim();
    if (
        configured.length >= 2
        && ['"', "'"].includes(configured[0])
        && configured.at(-1) === configured[0]
    ) {
        configured = configured.slice(1, -1).trim();
    }

    const candidate = configured || requestBaseUrl;
    if (!candidate) {
        return fallbackBaseUrl
            ? resolvePublicBaseUrl(fallbackBaseUrl, '')
            : null;
    }

    let url;
    try {
        url = new URL(candidate);
    } catch {
        if (fallbackBaseUrl) return resolvePublicBaseUrl(fallbackBaseUrl, '');
        throw new Error('PUBLIC_BASE_URL must be a valid absolute URL, for example https://eshansayhan-hotlink.hf.space.');
    }

    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
        if (fallbackBaseUrl) return resolvePublicBaseUrl(fallbackBaseUrl, '');
        throw new Error('PUBLIC_BASE_URL must be an HTTP(S) base URL without credentials, query, or fragment.');
    }

    const isLoopback = url.hostname === 'localhost'
        || url.hostname === '[::1]'
        || /^127(?:\.\d{1,3}){3}$/.test(url.hostname);
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && isLoopback)) {
        if (fallbackBaseUrl) return resolvePublicBaseUrl(fallbackBaseUrl, '');
        throw new Error('PUBLIC_BASE_URL must use HTTPS except for local loopback development.');
    }

    if (!configured && !isLoopback) {
        return fallbackBaseUrl
            ? resolvePublicBaseUrl(fallbackBaseUrl, '')
            : null;
    }
    return url.toString().replace(/\/+$/, '');
}
