# Signing: making tampering evident

## Threat model, plainly

The stable digest alone catches corruption and careless edits — but anyone who edits a bundle can recompute the digest and re-seal it. A detached signature closes that hole: re-sealing a tampered bundle invalidates the signature, and forging a new one requires the signer's private key.

The signed payload is the canonical JSON of the bundle **without** its `signatures` field. It therefore covers everything else — including `bundle_digest` and the volatile fields (`run_id`, `created_at`, step timestamps) that the stable digest deliberately ignores. Backdating a signed bundle breaks its signature.

Signatures never change what a bundle proves: they are excluded from the stable digest and from semantic diffs, so a signed bundle still diffs empty against its unsigned twin.

## Quickstart

```bash
pip install "proofline[sign]"

proofline keygen --out keys/
proofline sign run.json --key keys/proofline-signing.pem
proofline verify run.json
# OK run.json  (signature checked as part of verification)

proofline verify run.json --signed-by keys/proofline-signing.pub.pem
# OK run.json  (and it was signed by *this* key)
```

`proofline verify` always validates any signatures a bundle carries; a signed bundle with a broken signature fails verification. `--signed-by` additionally pins identity: the bundle must carry a valid signature from that exact public key.

Python API: `proofline.sign` exposes `generate_keypair`, `sign_bundle`, `verify_signatures`, and `signed_by`. Bundles can carry multiple signatures; each must verify.

## Key handling

- The private key is an unencrypted PKCS8 PEM (mode `0600` on POSIX). Store it like any deploy key: CI secret store, not the repository.
- An embedded public key proves integrity under that key. Proving *who* signed requires comparing against a key you trust (`--signed-by`), distributed out of band — for example, committed to the repository that consumes the bundles.
- There is no revocation or expiry in v1. Rotating a key means re-signing what still matters with the new one.

## Keyless signing and transparency logs (CI)

For CI-produced bundles you can skip key custody entirely with [Sigstore](https://www.sigstore.dev/): a bundle is just a file, so the official tooling works as-is and also records the signature in the public Rekor transparency log.

```yaml
# in GitHub Actions, after the bundle is produced
- run: pipx run sigstore sign --oidc-disable-ambient-providers=false ci/run.json
# verification, anywhere:
- run: pipx run sigstore verify github --cert-identity <workflow-ref> ci/run.json
```

This gives identity ("signed by this repository's workflow"), timestamps, and an append-only public record — without any private key to manage. Native Ed25519 signatures and Sigstore compose: use native signing for offline or key-pinned flows, Sigstore for CI provenance.
