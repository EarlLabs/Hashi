# secrets/ — the operator's real credentials, kept off every server that can be seized

Everything in this directory is ignored by git **except this README and the
`*.example` templates** (see `.gitignore`). Real files live here, on the owner's own
machine. Keep a second copy somewhere that is not this laptop, such as a password manager
or an encrypted USB stick. Without them a lost control plane cannot be rebuilt.

Nothing here belongs on a node. The only file that also lives on a server is
`server.env`, which is the control plane's `.env`.

| File | What it is | How it is made | Where else it lives |
|---|---|---|---|
| `server.env` | The control plane's `.env`, the copy the owner keeps | `cp .env.example secrets/server.env`, then fill it in. Its comments explain every value | On the control-plane host as `.env` (mode 600). Nowhere else |
| `operator-password.txt` | The panel password, one line. The server holds only its hash | Choose one of 12+ characters, then put the line `make hash-password` prints into `server.env` | Only here |
| `hashi-backup-identity.txt` | The **secret** half of the backup encryption key. Without it no backup can be read | `age-keygen -o secrets/hashi-backup-identity.txt`. The public key it prints goes into `HASHI_BACKUP_AGE_RECIPIENT` | **Never on the server.** Here and in the second copy |
| `restore.env` | What `make restore-from-bucket` needs on a new machine | Copy `restore.env.example` and fill it in | Only here |
| `mgmt/<device>.conf`, `mgmt/*-qr.png` | One management-tunnel config per device (laptop, phone, …) | `HASHI_MGMT_CONFIGS_TO=<dir> make mgmt-tunnel` on the control-plane host, then copy the files here. The script keeps no copy | On the device that uses it |

Also keep: `~/.ssh/hashi-node`, the private key the control plane uses to reach nodes.
The panel holds an encrypted copy. It is the only copy outside the database.

## Rules

- **Two different bucket keys.** The key in `server.env` (`HASHI_BACKUP_S3_*`) may only
  **write**. The key in `restore.env` (`HASHI_RESTORE_S3_*`) may only **read**. If they are
  the same key, whoever seizes the server can read or delete every backup.
- **Never paste a value from here into a chat, an issue or a log.** That includes a
  subscription URL: it is a bearer credential.
- Files stay mode `600` and the directory stays `700`.
