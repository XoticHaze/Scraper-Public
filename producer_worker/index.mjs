import {
  createCipheriv, createDecipheriv, createHash, createPrivateKey, createPublicKey,
  diffieHellman, generateKeyPairSync, hkdfSync, randomBytes, sign as rsaSign,
} from 'node:crypto';
import { gzipSync } from 'node:zlib';

const SCHEMA = 'repo-app-ephemeral-x25519-v1';
const AUTHORITY = 'private_compute_only';
const INFO = Buffer.from(SCHEMA, 'utf8');
const PUBLIC_REPO_DEFAULT = 'XoticHaze/Scraper-Public';
const PRIVATE_REPO_DEFAULT = 'XoticHaze/Scraper';
const EXCHANGE_REF_DEFAULT = 'rendezvous-exchange';

const b64 = (buf) => Buffer.from(buf).toString('base64');
const b64d = (s) => Buffer.from(String(s), 'base64');
const b64url = (buf) => Buffer.from(buf).toString('base64url');
const sha256 = (buf) => createHash('sha256').update(buf).digest('hex');
const keyId = (raw) => `sha256:${sha256(raw)}`;

function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${stable(value[k])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

export function aadBytes({ run_id, contract_id, contract_version, direction, recipient_key_id }) {
  return Buffer.from(stable({
    schema: SCHEMA,
    run_id: String(run_id),
    authority: AUTHORITY,
    contract_id,
    contract_version: String(contract_version),
    direction,
    recipient_key_id,
  }), 'utf8');
}

function rawPublicToKey(raw) {
  return createPublicKey({ key: { kty: 'OKP', crv: 'X25519', x: b64url(raw) }, format: 'jwk' });
}

function publicRaw(key) {
  const jwk = key.export({ format: 'jwk' });
  return Buffer.from(jwk.x, 'base64url');
}

export function generateResultRecipient() {
  const { privateKey, publicKey } = generateKeyPairSync('x25519');
  const raw = publicRaw(publicKey);
  return {
    private_jwk: privateKey.export({ format: 'jwk' }),
    public: { recipient_b64: b64(raw), recipient_key_id: keyId(raw) },
  };
}

export function encryptPayload(plaintext, recipient) {
  const recipientRaw = b64d(recipient.recipient_b64);
  if (recipientRaw.length !== 32 || keyId(recipientRaw) !== recipient.recipient_key_id) throw new Error('recipient_mismatch');
  const { privateKey, publicKey } = generateKeyPairSync('x25519');
  const senderRaw = publicRaw(publicKey);
  const aad = aadBytes(recipient);
  const shared = diffieHellman({ privateKey, publicKey: rawPublicToKey(recipientRaw) });
  const key = Buffer.from(hkdfSync('sha256', shared, createHash('sha256').update(aad).digest(), INFO, 32));
  const nonce = randomBytes(12);
  const cipher = createCipheriv('chacha20-poly1305', key, nonce, { authTagLength: 16 });
  cipher.setAAD(aad, { plaintextLength: plaintext.length });
  const body = Buffer.concat([cipher.update(plaintext), cipher.final(), cipher.getAuthTag()]);
  return {
    ciphertext: body,
    meta: {
      schema: SCHEMA,
      run_id: String(recipient.run_id),
      authority: AUTHORITY,
      contract_id: recipient.contract_id,
      contract_version: String(recipient.contract_version),
      direction: recipient.direction,
      recipient_key_id: recipient.recipient_key_id,
      sender_public_b64: b64(senderRaw),
      nonce_b64: b64(nonce),
      ciphertext_sha256: sha256(body),
      plaintext_sha256: sha256(plaintext),
    },
  };
}

export function decryptPayload(envelope, ciphertext, privateJwk) {
  if (sha256(ciphertext) !== envelope.ciphertext_sha256) throw new Error('ciphertext_digest_mismatch');
  const privateKey = createPrivateKey({ key: privateJwk, format: 'jwk' });
  const recipientRaw = Buffer.from(privateJwk.x, 'base64url');
  if (keyId(recipientRaw) !== envelope.recipient_key_id) throw new Error('result_recipient_mismatch');
  const senderRaw = b64d(envelope.sender_public_b64);
  const aad = aadBytes(envelope);
  const shared = diffieHellman({ privateKey, publicKey: rawPublicToKey(senderRaw) });
  const key = Buffer.from(hkdfSync('sha256', shared, createHash('sha256').update(aad).digest(), INFO, 32));
  const nonce = b64d(envelope.nonce_b64);
  const tag = ciphertext.subarray(ciphertext.length - 16);
  const body = ciphertext.subarray(0, ciphertext.length - 16);
  const decipher = createDecipheriv('chacha20-poly1305', key, nonce, { authTagLength: 16 });
  decipher.setAAD(aad, { plaintextLength: body.length });
  decipher.setAuthTag(tag);
  const plain = Buffer.concat([decipher.update(body), decipher.final()]);
  if (sha256(plain) !== envelope.plaintext_sha256) throw new Error('plaintext_digest_mismatch');
  return plain;
}

function octal(value, width) {
  const s = Math.trunc(value).toString(8);
  return `${'0'.repeat(Math.max(0, width - s.length - 1))}${s}\0`;
}

function tarHeader(name, size) {
  if (!name || name.length > 99 || name.includes('..') || name.startsWith('/')) throw new Error(`unsafe_tar_path:${name}`);
  const h = Buffer.alloc(512, 0);
  h.write(name, 0, 100, 'utf8');
  h.write(octal(0o600, 8), 100, 8, 'ascii');
  h.write(octal(0, 8), 108, 8, 'ascii'); h.write(octal(0, 8), 116, 8, 'ascii');
  h.write(octal(size, 12), 124, 12, 'ascii'); h.write(octal(0, 12), 136, 12, 'ascii');
  h.fill(0x20, 148, 156); h[156] = '0'.charCodeAt(0);
  h.write('ustar\0', 257, 6, 'ascii'); h.write('00', 263, 2, 'ascii');
  const sum = [...h].reduce((a, b) => a + b, 0);
  h.write(`${octal(sum, 8)}`, 148, 8, 'ascii');
  return h;
}

export function buildWorkloadTarGz(files, manifest) {
  const parts = [];
  const all = [...files, { path: 'workload-manifest.json', bytes: Buffer.from(`${stable(manifest)}\n`, 'utf8') }];
  for (const file of all) {
    const bytes = Buffer.from(file.bytes);
    parts.push(tarHeader(file.path, bytes.length), bytes);
    const pad = (512 - (bytes.length % 512)) % 512;
    if (pad) parts.push(Buffer.alloc(pad));
  }
  parts.push(Buffer.alloc(1024));
  return gzipSync(Buffer.concat(parts), { level: 6, mtime: 0 });
}

function splitCiphertext(ciphertext, root, chunkChars = 700000) {
  const encoded = b64(ciphertext);
  const files = [], nodes = [];
  for (let i = 0, n = 0; i < encoded.length; i += chunkChars, n += 1) {
    const body = encoded.slice(i, i + chunkChars);
    const path = `${root}/chunk-${String(n).padStart(4, '0')}.b64`;
    files.push({ path, body });
    nodes.push({ path, sha256: sha256(Buffer.from(body, 'ascii')), chars: body.length });
  }
  return { files, nodes };
}

function appJwt(env) {
  const now = Math.floor(Date.now() / 1000);
  const head = b64url(Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })));
  const body = b64url(Buffer.from(JSON.stringify({ iat: now - 60, exp: now + 540, iss: String(env.GITHUB_APP_ID) })));
  const input = `${head}.${body}`;
  const sig = rsaSign('RSA-SHA256', Buffer.from(input), createPrivateKey(env.GITHUB_APP_PRIVATE_KEY));
  return `${input}.${b64url(sig)}`;
}

async function installationToken(env, repos) {
  const response = await fetch(`https://api.github.com/app/installations/${env.GITHUB_INSTALLATION_ID}/access_tokens`, {
    method: 'POST', headers: ghHeaders(`Bearer ${appJwt(env)}`),
    body: JSON.stringify({ repositories: repos.map((r) => r.split('/')[1]), permissions: { contents: 'write' } }),
  });
  if (!response.ok) throw new Error(`installation_token:${response.status}`);
  return (await response.json()).token;
}

function ghHeaders(auth) {
  return { accept: 'application/vnd.github+json', authorization: auth, 'content-type': 'application/json', 'user-agent': 'repo-app-private-envelope-producer', 'x-github-api-version': '2022-11-28' };
}

async function ghJson(token, url, optional = false) {
  const r = await fetch(url, { headers: ghHeaders(`Bearer ${token}`) });
  if (optional && r.status === 404) return null;
  if (!r.ok) throw new Error(`github_get:${r.status}:${url}`);
  return r.json();
}

async function readFile(token, repo, path, ref = 'main', optional = false) {
  const node = await ghJson(token, `https://api.github.com/repos/${repo}/contents/${path}?ref=${encodeURIComponent(ref)}`, optional);
  if (!node) return null;
  if (node.type !== 'file') throw new Error(`not_file:${path}`);
  return Buffer.from(String(node.content || '').replace(/\n/g, ''), 'base64');
}

async function putFile(token, repo, path, ref, bytes, message) {
  const existing = await ghJson(token, `https://api.github.com/repos/${repo}/contents/${path}?ref=${encodeURIComponent(ref)}`, true);
  const body = { message, content: b64(bytes), branch: ref };
  if (existing?.sha) body.sha = existing.sha;
  const r = await fetch(`https://api.github.com/repos/${repo}/contents/${path}`, { method: 'PUT', headers: ghHeaders(`Bearer ${token}`), body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`github_put:${r.status}:${path}`);
}

async function readPrivatePayload(token, repo, basePath) {
  const queue = [basePath.replace(/\/$/, '')], files = [];
  let total = 0;
  while (queue.length) {
    const path = queue.shift();
    const nodes = await ghJson(token, `https://api.github.com/repos/${repo}/contents/${path}?ref=main`);
    if (!Array.isArray(nodes)) throw new Error(`payload_path_not_directory:${path}`);
    for (const node of nodes) {
      if (node.type === 'dir') { queue.push(node.path); continue; }
      if (node.type !== 'file') throw new Error(`unsupported_private_payload_node:${node.path}`);
      if (files.length >= 64) throw new Error('private_payload_too_many_files');
      const bytes = await readFile(token, repo, node.path, 'main');
      total += bytes.length;
      if (bytes.length > 2_000_000 || total > 12_000_000) throw new Error('private_payload_too_large');
      const rel = node.path.slice(basePath.replace(/\/$/, '').length + 1);
      if (!rel || rel.includes('..') || rel.startsWith('.github/') || rel.startsWith('.git/')) throw new Error(`unsafe_private_path:${rel}`);
      files.push({ path: rel, bytes });
    }
  }
  return files.sort((a,b) => a.path.localeCompare(b.path));
}

async function publicRequest(token, publicRepo, exchangeRef, runId, contractId) {
  const raw = await readFile(token, publicRepo, `rendezvous/recipients/${runId}/request.json`, exchangeRef);
  const request = JSON.parse(raw.toString('utf8'));
  if (String(request.run_id) !== String(runId) || request.contract_id !== contractId) throw new Error('request_binding_mismatch');
  return request;
}

async function privateRegistry(token, privateRepo) {
  const raw = await readFile(token, privateRepo, 'producer/workloads.json', 'main');
  const doc = JSON.parse(raw.toString('utf8'));
  if (doc.schema !== 'repo-app-private-workload-registry-v1') throw new Error('private_registry_schema');
  return doc;
}

export async function processRun(env, runId, contractId) {
  if (!/^\d+$/.test(String(runId)) || !/^[a-z0-9][a-z0-9._-]{0,63}$/.test(contractId)) throw new Error('invalid_run_or_contract');
  const publicRepo = env.PUBLIC_REPO || PUBLIC_REPO_DEFAULT;
  const privateRepo = env.PRIVATE_REPO || PRIVATE_REPO_DEFAULT;
  const exchangeRef = env.EXCHANGE_REF || EXCHANGE_REF_DEFAULT;
  const token = await installationToken(env, [publicRepo, privateRepo]);
  const statePath = `producer/state/${runId}/${contractId}.json`;
  if (await readFile(token, privateRepo, statePath, 'main', true)) return { status: 'already_processed' };

  const request = await publicRequest(token, publicRepo, exchangeRef, runId, contractId);
  const registry = await privateRegistry(token, privateRepo);
  const spec = registry.workloads?.[request.workload_id];
  if (!spec?.enabled || spec.contract_id !== contractId) throw new Error('workload_not_allowed');

  const recipientRaw = await readFile(token, publicRepo, `rendezvous/recipients/${runId}/${contractId}.json`, exchangeRef);
  const recipient = JSON.parse(recipientRaw.toString('utf8'));
  if (recipient.direction !== 'workload' || String(recipient.run_id) !== String(runId) || recipient.contract_id !== contractId) throw new Error('recipient_binding_mismatch');

  const files = await readPrivatePayload(token, privateRepo, spec.path);
  if (!files.some((f) => f.path === (spec.entrypoint || 'entrypoint.py'))) throw new Error('private_entrypoint_missing');
  const result = generateResultRecipient();
  const manifest = {
    schema: 'repo-app-private-workload-v1', contract_id: contractId, contract_version: String(recipient.contract_version),
    entrypoint: spec.entrypoint || 'entrypoint.py', files: Object.fromEntries(files.map((f) => [f.path, sha256(f.bytes)])),
    result_recipient_b64: result.public.recipient_b64, result_recipient_key_id: result.public.recipient_key_id,
  };
  const payload = buildWorkloadTarGz(files, manifest);
  const encrypted = encryptPayload(payload, { ...recipient, direction: 'workload' });
  const responseRoot = `rendezvous/responses/${runId}/${contractId}`;
  const split = splitCiphertext(encrypted.ciphertext, responseRoot);
  for (const file of split.files) await putFile(token, publicRepo, file.path, exchangeRef, Buffer.from(file.body, 'ascii'), `private compute ciphertext ${runId}`);
  const envelope = { ...encrypted.meta, chunks: split.nodes };
  await putFile(token, publicRepo, `${responseRoot}/workload-envelope.json`, exchangeRef, Buffer.from(`${stable(envelope)}\n`), `private compute envelope ${runId}`);
  const state = {
    schema: 'repo-app-private-producer-state-v1', run_id: String(runId), contract_id: contractId,
    contract_version: String(recipient.contract_version), workload_id: request.workload_id, result_private_jwk: result.private_jwk,
    result_root: `rendezvous/results/${runId}/${contractId}`, status: 'workload_published', created_at: new Date().toISOString(),
  };
  await putFile(token, privateRepo, statePath, 'main', Buffer.from(`${JSON.stringify(state, null, 2)}\n`), `producer state ${runId}`);
  return { status: 'published', workload_id: request.workload_id };
}

async function collectOne(env, token, publicRepo, privateRepo, exchangeRef, statePath, state) {
  if (state.status === 'result_stored') return false;
  const envRaw = await readFile(token, publicRepo, `${state.result_root}/result-envelope.json`, exchangeRef, true);
  if (!envRaw) return false;
  const envelope = JSON.parse(envRaw.toString('utf8'));
  const parts = [];
  for (const node of envelope.chunks || []) {
    const chunk = await readFile(token, publicRepo, node.path, exchangeRef);
    const body = chunk.toString('ascii').trim();
    if (body.length !== Number(node.chars) || sha256(Buffer.from(body, 'ascii')) !== node.sha256) throw new Error('result_chunk_mismatch');
    parts.push(body);
  }
  const ciphertext = Buffer.from(parts.join(''), 'base64');
  const plaintext = decryptPayload(envelope, ciphertext, state.result_private_jwk);
  const resultPath = `producer/results/${state.workload_id}/${state.run_id}-${state.contract_id}.tar.gz.b64`;
  await putFile(token, privateRepo, resultPath, 'main', Buffer.from(`${b64(plaintext)}\n`), `private compute result ${state.run_id}`);
  const updated = { ...state, status: 'result_stored', result_path: resultPath, completed_at: new Date().toISOString(), result_plaintext_sha256: sha256(plaintext) };
  await putFile(token, privateRepo, statePath, 'main', Buffer.from(`${JSON.stringify(updated, null, 2)}\n`), `complete producer state ${state.run_id}`);
  return true;
}

async function collectResults(env) {
  const publicRepo = env.PUBLIC_REPO || PUBLIC_REPO_DEFAULT, privateRepo = env.PRIVATE_REPO || PRIVATE_REPO_DEFAULT, exchangeRef = env.EXCHANGE_REF || EXCHANGE_REF_DEFAULT;
  const token = await installationToken(env, [publicRepo, privateRepo]);
  const root = await ghJson(token, `https://api.github.com/repos/${privateRepo}/contents/producer/state?ref=main`, true);
  if (!root) return 0;
  let done = 0;
  for (const runNode of [...root].filter((n) => n.type === 'dir').slice(-30)) {
    const contracts = await ghJson(token, `https://api.github.com/repos/${privateRepo}/contents/${runNode.path}?ref=main`);
    for (const node of contracts.filter((n) => n.type === 'file' && n.name.endsWith('.json'))) {
      const raw = await readFile(token, privateRepo, node.path, 'main');
      if (await collectOne(env, token, publicRepo, privateRepo, exchangeRef, node.path, JSON.parse(raw.toString('utf8')))) done += 1;
    }
  }
  return done;
}

async function catchUp(env) {
  const publicRepo = env.PUBLIC_REPO || PUBLIC_REPO_DEFAULT, privateRepo = env.PRIVATE_REPO || PRIVATE_REPO_DEFAULT, exchangeRef = env.EXCHANGE_REF || EXCHANGE_REF_DEFAULT;
  const token = await installationToken(env, [publicRepo, privateRepo]);
  const root = await ghJson(token, `https://api.github.com/repos/${publicRepo}/contents/rendezvous/recipients?ref=${encodeURIComponent(exchangeRef)}`, true);
  if (root) {
    const runs = [...root].filter((n) => n.type === 'dir').sort((a,b) => Number(b.name)-Number(a.name)).slice(0, 20);
    for (const run of runs) {
      const req = await readFile(token, publicRepo, `${run.path}/request.json`, exchangeRef, true);
      if (!req) continue;
      const body = JSON.parse(req.toString('utf8'));
      try { await processRun(env, String(body.run_id), String(body.contract_id)); } catch (e) { console.log(`producer_skip run=${body.run_id} ${e.message}`); }
    }
  }
  return collectResults(env);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'GET' && url.pathname === '/health') return Response.json({ ok: true, service: 'private-envelope-producer' });
    if (request.method === 'POST' && url.pathname === '/v1/private-compute/notify') {
      try {
        const body = await request.json();
        const result = await processRun(env, String(body.run_id || ''), String(body.contract_id || ''));
        return Response.json({ ok: true, ...result }, { status: 202 });
      } catch (e) {
        return Response.json({ ok: false, error: String(e.message || e) }, { status: 400 });
      }
    }
    return Response.json({ ok: false, error: 'not_found' }, { status: 404 });
  },
  async scheduled(controller, env, ctx) { ctx.waitUntil(catchUp(env)); },
};
