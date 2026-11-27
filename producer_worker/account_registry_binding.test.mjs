import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createHash } from 'node:crypto';
import { validatePrivateRegistry, validateResultBinding, generateResultRecipient } from './index.mjs';
const digest = 'a'.repeat(40);
const registry = () => ({schema:'repo-app-private-workload-registry-v3',version:3,private_actions_compute_selectable:false,
 execution_route_policy:'config/execution_route_mode_current.v1.json', trusted_public_runtime:{repository:'XoticHaze/Scraper-Public',
 workflow_path:'.github/workflows/encrypted-private-compute-runtime.yml',workflow_sha:digest,runtime_source_sha:digest}});
test('registry v3 exact route only', () => {
 assert.equal(validatePrivateRegistry(registry(),'XoticHaze/Scraper').version,3);
 for (const patch of [{schema:'repo-app-private-workload-registry-v2'},{private_actions_compute_selectable:true},{execution_route_policy:'other.json'},{version:2}])
  assert.throws(()=>validatePrivateRegistry({...registry(),...patch},'XoticHaze/Scraper'));
 assert.throws(()=>validatePrivateRegistry(registry(),'other/repo'));
 assert.throws(()=>validatePrivateRegistry({...registry(),trusted_public_runtime:{...registry().trusted_public_runtime,workflow_sha:'main'}},'XoticHaze/Scraper'));
});
test('result exact binding and chunk root', () => {
 const recipient=generateResultRecipient(), state={run_id:'123',contract_id:'python-bundle-v1',contract_version:'1',result_root:'rendezvous/results/123/python-bundle-v1',result_private_jwk:recipient.private_jwk};
 const envelope={schema:'repo-app-ephemeral-x25519-v1',authority:'private_compute_only',direction:'result',run_id:'123',contract_id:state.contract_id,contract_version:'1',recipient_key_id:recipient.public.recipient_key_id,chunks:[{path:state.result_root+'/chunk-0000.b64',chars:4,sha256:createHash('sha256').update('abcd').digest('hex')}]};
 validateResultBinding(envelope,state);
 for (const patch of [{run_id:'124'},{direction:'workload'},{contract_version:'2'},{recipient_key_id:'wrong'},{chunks:[]},{chunks:[{...envelope.chunks[0],path:'other/chunk-0000.b64'}]},{chunks:[{...envelope.chunks[0],chars:900001}]}])
  assert.throws(()=>validateResultBinding({...envelope,...patch},state));
});
