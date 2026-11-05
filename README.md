# ansible-proserver-mail

Mail role for FreeBSD [Proserver](https://infrastructure.punkt.de/de/produkte/proserver.html): runs either Sendmail (FreeBSD base) or
Postfix, manages `/etc/mail/aliases`, and optionally signs outgoing mail
with OpenDKIM. Keys, `KeyTable`/`SigningTable` and `opendkim.conf` are the
same for both MTAs — only the wiring differs.

The role installs no packages. OpenDKIM must already be installed when
DKIM is used (Proserver images ship it), and the `postfix` package when
`mail.mta` is `postfix`. Each DKIM selector's private key is either
supplied (typically via Ansible Vault) or generated on the host — see
`autogenerate` below.

## Role Variables

| Option | Description | Type | Required | Default |
|---|---|---|---|---|
| `mail.enable_mta` | `no` turns mail delivery off entirely (`sendmail_enable="NONE"`, Postfix stopped). `mail.dkim.domains` must then be empty. | bool | no | `yes` |
| `mail.mta` | `sendmail` or `postfix`. The role always makes that MTA the active one and stops the other — see "Sendmail and Postfix" below. | string | no | `sendmail` |
| `mail.aliases` | Entries for `/etc/mail/aliases`, used by both MTAs. | dict | no | `{}` |
| `mail.sendmail.mc_file` | Sendmail `.mc` file the DKIM milter line is added to. | string | no | `/etc/mail/<hostname>.mc` |
| `mail.sendmail.cf_file` | Compiled Sendmail config that must exist before the DKIM milter is wired in. | string | no | `/etc/mail/<hostname>.cf` |
| `mail.postfix.main_cf` | Additional `main.cf` parameters applied with `postconf -e`. With DKIM, `milter_default_action` is always taken from `mail.dkim.on_failure`. | dict | no | `{inet_interfaces: loopback-only}` |
| `mail.dkim.domains` | Domains and their selectors — see below. OpenDKIM is only set up, and wired into the MTA, when this is non-empty; emptying it unwires the milter again. | dict | no | `{}` |
| `mail.dkim.on_failure` | What happens to outgoing mail that can't be signed (OpenDKIM down, unreachable, or failing): `tempfail` keeps it queued in the MTA and retries, `accept` sends it unsigned. Applied to OpenDKIM (`On-Default`), Postfix (`milter_default_action`) and Sendmail (`F=T`) alike — see "Failure handling" below. | string | no | `tempfail` |
| `mail.dkim.trusted_hosts` | Hosts/networks allowed to relay signed mail without verification (`TrustedHosts`). | list | no | `[127.0.0.1, localhost]` |
| `mail.dkim.key_size` | Default RSA key size used when generating a key (per-selector `key_size` overrides this). | int | no | `2048` |
| `mail.dkim.prefix.config` | Directory holding `opendkim.conf`, `KeyTable`, `SigningTable`, `TrustedHosts`, and `keys/`. Also written to `milteropendkim_cfgfile` in `rc.conf`, so a non-default path takes effect. | string | no | `/usr/local/etc/mail` |
| `mail.dkim.socket` | OpenDKIM milter socket (`local:/path` or `inet:port@host`). Used for `opendkim.conf`, the Sendmail `INPUT_MAIL_FILTER` line, and — translated to Postfix syntax — `smtpd_milters`/`non_smtpd_milters`. | string | no | `local:/var/run/milteropendkim/milteropendkim.sock` |
| `mail.manage_services` | **Testing only.** `no` writes OpenDKIM's files and the Sendmail `.mc` under the configured paths but touches no services, `rc.conf`, aliases or other system files, skips ownership changes, and skips the Postfix side entirely (it only exists as live `postconf` state). Never set it to `no` on a real host. | bool | no | `yes` |

DKIM files and keys are always owned by `mailnull`: FreeBSD's
`milter-opendkim` service runs OpenDKIM as that user regardless of
configuration, and Postfix joins that group to reach the socket.

With DKIM on Sendmail, the role first checks that `/etc/mail/<hostname>.cf`
already exists (FreeBSD builds this file from the matching `.mc` when
Sendmail is set up). If it doesn't, the role fails — wiring a milter into a
Sendmail config that was never actually built would silently do nothing.

### Sendmail and Postfix

`mail.mta: sendmail` sets `sendmail_enable="NO"` (the localhost-only
daemon FreeBSD runs by default) and starts Sendmail.

`mail.mta: postfix` makes Postfix the host's MTA: it checks that the
`postfix` package is installed, sets `sendmail_enable="NONE"` and
`postfix_enable="YES"` in `rc.conf`, installs Postfix's `mailer.conf`,
disables Sendmail's periodic jobs, builds Postfix's own alias database
(`/etc/aliases.db` from `/etc/aliases` → `/etc/mail/aliases`) whenever
it's missing or older than its source, and applies `mail.postfix.main_cf`.
With DKIM it also adds the `postfix` user to the `mailnull` group (the
milter socket is mode `0770`). `inet_interfaces` defaults to
`loopback-only`, matching the localhost-only Sendmail it replaces.

Only one MTA runs at a time, and this is enforced on every run (not just
when something changed):

- `mta: postfix` stops any Sendmail daemon still running — including the
  client queue runner, which `rc.d/sendmail` no longer manages once
  `sendmail_enable="NONE"` — by signalling it through its pidfile.
- `mta: sendmail` (and `enable_mta: no`) switches back: removes
  `postfix_enable`, stops Postfix, restores Sendmail's `mailer.conf` and
  periodic jobs, then enables (or disables) Sendmail.

Changes to `mail.aliases` run `newaliases`, which goes to whichever MTA
`mailer.conf` points at.

### Failure handling

OpenDKIM runs in **sign-only mode** (`Mode s`). Signing reads keys from
local files and never queries DNS, so a DNS outage — or a selector whose
TXT record isn't published yet — can't delay or block outgoing mail. (A
missing or wrong DNS record makes *receivers* fail the signature; it never
affects sending.) Verifying incoming mail is left off: these hosts only
send, and it would make mail flow depend on DNS lookups.

With the default `mail.dkim.on_failure: tempfail`, the setup heals itself:

| Failure | What happens |
|---|---|
| OpenDKIM's filter process crashes | OpenDKIM restarts it itself (`AutoRestart`), up to 10 times per hour, then gives up to avoid a restart loop. |
| OpenDKIM is stopped or its socket is unreachable | Postfix/Sendmail tempfail the message: it stays queued and is retried automatically (Postfix: queue/maildrop rescans; Sendmail: queue runs every 30 minutes). Once OpenDKIM is back, the mail goes out signed. |
| OpenDKIM can't sign a message (e.g. unreadable key) | Tempfail as above, so nothing is sent unsigned; the reason is logged. |
| Problem not fixed in time | The MTA bounces the mail after its queue lifetime (5 days by default). |

Mail held back this way only shows up as a growing queue (`mailq`), so
monitor queue size. `SyslogSuccess` logs every signature OpenDKIM adds to
`/var/log/maillog`, so signing can be confirmed from the log.

Set `mail.dkim.on_failure: accept` if mail must never be delayed: it is
then sent unsigned while OpenDKIM is unavailable, which receivers enforcing
DMARC may reject or junk.

### `mail.dkim.domains` structure

A dict keyed by domain, each with one or more selectors (multiple
selectors per domain support key rotation):

```yaml
mail:
  dkim:
    domains:
      example.com:
        selectors:
          default:
            private_key: "{{ secrets.dkim.example_com_default }}"
            active: yes
      another-example.com:
        selectors:
          "2025":
            private_key: "{{ secrets.dkim.another_example_com_2025 }}"
            active: no        # kept for verification, not currently signing
          "2026":
            private_key: "{{ secrets.dkim.another_example_com_2026 }}"
            active: yes
```

Per-selector fields:

| Field | Required | Default | Meaning |
|---|---|---|---|
| `private_key` | exactly one of `private_key` / `autogenerate: true` is required | — | PEM-encoded RSA private key content. The role fails with a clear error naming the domain/selector if neither this nor `autogenerate: true` is set — or if both are set. |
| `autogenerate` | see above | `false` | Declares that this selector's key is generated on the host rather than supplied. Actual generation only happens when the play is run with `--tags dkim_generate_keys` — see "Generating a key" below. Never regenerates/rotates a key file that already exists. |
| `active` | no | `no` | Whether this selector signs outgoing mail (`SigningTable`). Defaults to `no` for every selector, supplied or generated — a key must never sign mail until its DNS TXT record is confirmed published and propagated, which requires an explicit, deliberate `active: yes`. Inactive selectors still get a `KeyTable` entry and a key file on disk — useful mid-rotation. Multiple selectors for the same domain may be `active: yes` simultaneously (see `MultipleSignatures` in `opendkim.conf`). |
| `key_size` | no | `mail.dkim.key_size` (`2048`) | RSA key size used only when this selector's key is being generated (`autogenerate: true`). Ignored for supplied keys. |

A selector with `autogenerate: true` but no key file yet is left out of
`KeyTable`/`SigningTable`/the DNS report until it's actually generated — the
role prints a note (`... is set to autogenerate but has no key file yet ...`)
rather than referencing a file that doesn't exist.

## Generating a key

**Supplying your own key** (no extra tag needed):

```sh
opendkim-genkey -D /tmp -d example.com -s default -b 2048
# /tmp/default.private now holds the PEM private key.
```

Store its content in `group_vars/secrets.yml`, encrypted with
`ansible-vault encrypt group_vars/secrets.yml`, then reference it:

```yaml
secrets:
  dkim:
    example_com_default: |
      -----BEGIN PRIVATE KEY-----
      ...
      -----END PRIVATE KEY-----

mail:
  dkim:
    domains:
      example.com:
        selectors:
          default:
            private_key: "{{ secrets.dkim.example_com_default }}"
```

**Letting the role generate one for you:** declare the selector with
`autogenerate: true` and no `private_key`:

```yaml
mail:
  dkim:
    domains:
      example.com:
        selectors:
          default:
            autogenerate: true   # no private_key — role generates a key
            # active defaults to "no" — flip to "yes" only after the DNS TXT
            # record below has been published and propagated.
```

A normal run of the play will validate this config and
report that the key doesn't exist yet, but **will not** create it — key
generation is deliberately excluded from every default run so the role can
never mint a keypair as a side effect of an ordinary apply. To actually
generate it, run the play once with the dedicated tag:

```sh
ansible-playbook playbook.yml --limit <host> --tags dkim_generate_keys
```

This creates the key file (idempotently — it's a no-op if the file already
exists) but skips the rest of the role, since that invocation only matches
tasks tagged `dkim_generate_keys`. Follow it with a normal run to actually
wire the new key into `KeyTable`/`SigningTable` and get its DNS record:

```sh
ansible-playbook playbook.yml --limit <host>
```

Check the `Report required DNS TXT records` task output for the record to
publish. The key, once generated, is left in place on every later run
regardless of tags — the role never rotates or overwrites an existing key
file.

## Dependencies

None.

## Installation

Add this role to the requirements.yml of your playbook as follows:

```yaml
roles:
  - name: ansible-proserver-mail
    src: https://github.com/punktDe/ansible-proserver-mail
```

Afterwards, install the role by running `ansible-galaxy install -r requirements.yml`.

## Example Playbook

```yaml
- hosts: all
  roles:
    - name: ansible-proserver-mail
  vars:
    mail:
      mta: postfix
      dkim:
        domains:
          example.com:
            selectors:
              default:
                private_key: "{{ secrets.dkim.example_com_default }}"
                active: yes
```

## Testing

Tests use [Molecule](https://ansible.readthedocs.io/projects/molecule/)
(`pip install molecule`) and run from the repository root:

| Scenario | Runs on | Covers |
|---|---|---|
| `default` | the controller itself (macOS/Linux) | generated `KeyTable`/`SigningTable`/`opendkim.conf`, Sendmail `.mc` wiring, key file handling, idempotence |
| `postfix` | a disposable FreeBSD VM | full Postfix switch, alias database, milter socket access, a real mail signed and verified, recovery after an OpenDKIM outage |
| `sendmail` | a disposable FreeBSD VM | the same for Sendmail |

```sh
molecule test                     # default scenario, safe anywhere

# FreeBSD scenarios replace the target's MTA — throwaway VMs only.
MAIL_MOLECULE_DISPOSABLE=yes MAIL_MOLECULE_HOST=<vm> molecule test -s postfix
MAIL_MOLECULE_DISPOSABLE=yes MAIL_MOLECULE_HOST=<vm> molecule test -s sendmail
```

The FreeBSD scenarios connect as `root` over SSH (`MAIL_MOLECULE_HOST`,
default `freebsd`) or locally with `MAIL_MOLECULE_CONNECTION=local` when
run inside the VM. They need no DNS: converge saves the TXT records the
role reports, and verify checks the delivered mail's signature against
exactly those records using `dkimpy` with an injected lookup
(`molecule/resources/files/verify_dkim.py`), so a wrong DNS record fails
the test as well.
