import fs from 'node:fs';
import { encryptPayload } from './index.mjs';

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const plaintext = Buffer.from(input.plaintext_b64, 'base64');
const encrypted = encryptPayload(plaintext, input.recipient);
process.stdout.write(JSON.stringify({ meta: encrypted.meta, ciphertext_b64: encrypted.ciphertext.toString('base64') }));
