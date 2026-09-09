import fs from 'node:fs';
import { createHash } from 'node:crypto';
import { buildWorkloadTarGz, encryptPayload, generateResultRecipient } from './index.mjs';

const input = JSON.parse(fs.readFileSync(0, 'utf8'));

if (input.mode === 'full-workload') {
  const recipient = input.recipient;
  const entrypointBytes = Buffer.from(
    "from pathlib import Path\nimport os\nout=Path(os.environ['REPO_APP_PRIVATE_OUTPUT'])\nout.mkdir(parents=True, exist_ok=True)\n(out/'proof.txt').write_text('producer-full-round-trip-ok\\n', encoding='utf-8')\nprint('PRIVATE_NODE_PRODUCER_STDOUT')\n",
    'utf8',
  );
  const result = generateResultRecipient();
  const manifest = {
    schema: 'repo-app-private-workload-v1',
    contract_id: recipient.contract_id,
    contract_version: String(recipient.contract_version),
    entrypoint: 'entrypoint.py',
    files: { 'entrypoint.py': createHash('sha256').update(entrypointBytes).digest('hex') },
    result_recipient_b64: result.public.recipient_b64,
    result_recipient_key_id: result.public.recipient_key_id,
  };
  const payload = buildWorkloadTarGz([{ path: 'entrypoint.py', bytes: entrypointBytes }], manifest);
  const encrypted = encryptPayload(payload, recipient);
  process.stdout.write(JSON.stringify({
    meta: encrypted.meta,
    ciphertext_b64: encrypted.ciphertext.toString('base64'),
    result_private_raw_b64: Buffer.from(result.private_jwk.d, 'base64url').toString('base64'),
    result_recipient: result.public,
  }));
} else {
  const plaintext = Buffer.from(input.plaintext_b64, 'base64');
  const encrypted = encryptPayload(plaintext, input.recipient);
  process.stdout.write(JSON.stringify({ meta: encrypted.meta, ciphertext_b64: encrypted.ciphertext.toString('base64') }));
}
