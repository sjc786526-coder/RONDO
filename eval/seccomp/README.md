# Plan 008 namespace diagnostic profile

`plan008-userns-minimal-v0.2.3.json` is an opt-in Plan 008 container profile
used by the bounded namespace diagnosis and by the no-API/paid Terminal-Bench
paths whose tracked pair contract requires it. It is never the RONDO host or
Docker daemon default and must not be applied globally.

The additional allow rule is nevertheless container-wide: the kernel does not
bind it to the frozen bubblewrap binary or the diagnostic process. Every process
inside that container without `CAP_SYS_ADMIN` is evaluated against the same rule.

- Upstream: `moby/profiles`, tag `seccomp/v0.2.3`
- Tag object: `f1a0fd6b5a369fca061b041539129661ed337ef5`
- Peeled commit: `836ae4d37ef2ec995c77c99fc55f5b5f3af3a897`
- Source URL: `https://raw.githubusercontent.com/moby/profiles/seccomp/v0.2.3/seccomp/default.json`
- Source SHA-256: `536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74`
- Derived SHA-256: `9c5198e529f03d38babe9f270f663fa6867bda4e4d14a37a1f6680179d9bbd2f`
- Canonical effective JSON SHA-256: `a67068e2712d6dd8168d96c71e5e46df2ec74e1ef7c6e49bf54447c5a12fa3bf`

The only semantic delta is one `SCMP_ACT_ALLOW` rule, excluded when
`CAP_SYS_ADMIN` is present, for `clone`, `mount`, `pivot_root`, `umount2`, and
`unshare`. Frozen bubblewrap uses raw `clone`, `mount`, `pivot_root`, and
`umount2`; the independent diagnostic uses `unshare(CLONE_NEWUSER)`.
`clone3` remains the upstream `ENOSYS` fallback and `setns` remains unchanged.
At the byte level the derived file also has one final LF while the upstream raw
file has none; validation removes that LF and the exact rule block before
requiring the upstream SHA-256 above.

The observed Docker Engine version is recorded separately by the execution
log; it does not change this profile's upstream identity. Every run must retain
`--cap-drop ALL`, reject `privileged`, `SYS_ADMIN`, and `seccomp=unconfined`,
and verify the daemon-inspected canonical JSON digest through the supervisor.
The original derived-file SHA remains a separate source identity because the
Docker daemon reserializes the profile before returning `SecurityOpt`.
