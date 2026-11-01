"""Synthetic-only regression tests for versioned public encrypted-compute metadata."""
import hashlib
import unittest

from encrypted_compute.transport import (
    SCHEMA, assemble_chunks, decrypt_bytes, encrypt_bytes,
    generate_recipient, split_ciphertext, validate_envelope,
)


class PublicMetadataV2Tests(unittest.TestCase):
    def setUp(self):
        self.run = "synthetic-run-1"
        self.contract = "python-bundle-v1"
        self.version = "1"
        self.recipient = generate_recipient(
            run_id=self.run, contract_id=self.contract,
            contract_version=self.version, direction="workload",
        )
        self.plaintext = b"synthetic-only-no-private-source"
        self.ciphertext, self.meta = encrypt_bytes(
            self.plaintext,
            recipient_public_b64=self.recipient.public["recipient_b64"],
            run_id=self.run, contract_id=self.contract,
            contract_version=self.version, direction="workload",
        )
        files, descriptors = split_ciphertext(
            self.ciphertext, root="rendezvous/responses/synthetic-run-1"
        )
        self.envelope = dict(self.meta, chunks=descriptors)
        self.chunks = dict(files)

    def test_public_metadata_never_contains_plaintext_digest(self):
        self.assertEqual(SCHEMA, "repo-app-ephemeral-x25519-v2")
        self.assertNotIn("plaintext_sha256", self.envelope)
        self.assertNotIn(
            hashlib.sha256(self.plaintext).hexdigest(),
            str(self.envelope),
        )
        self.assertEqual(
            self.envelope["ciphertext_sha256"],
            hashlib.sha256(self.ciphertext).hexdigest(),
        )

    def test_authenticated_roundtrip(self):
        body = assemble_chunks(self.envelope, self.chunks)
        self.assertEqual(
            decrypt_bytes(
                envelope=self.envelope, ciphertext=body,
                private_key_b64=self.recipient.private_b64,
                expected_run_id=self.run, expected_contract_id=self.contract,
                expected_contract_version=self.version,
                expected_direction="workload",
                response_root="rendezvous/responses/synthetic-run-1",
            ),
            self.plaintext,
        )

    def test_reject_legacy_public_plaintext_digest_field(self):
        bad = dict(self.envelope, plaintext_sha256="0" * 64)
        with self.assertRaises(RuntimeError):
            validate_envelope(
                bad, expected_run_id=self.run,
                expected_contract_id=self.contract,
                expected_contract_version=self.version,
                expected_direction="workload",
                response_root="rendezvous/responses/synthetic-run-1",
            )

    def test_reject_ciphertext_tampering(self):
        changed = bytes([self.ciphertext[0] ^ 1]) + self.ciphertext[1:]
        with self.assertRaises(RuntimeError):
            decrypt_bytes(
                envelope=self.envelope, ciphertext=changed,
                private_key_b64=self.recipient.private_b64,
                expected_run_id=self.run, expected_contract_id=self.contract,
                expected_contract_version=self.version,
                expected_direction="workload",
                response_root="rendezvous/responses/synthetic-run-1",
            )


if __name__ == "__main__":
    unittest.main()
