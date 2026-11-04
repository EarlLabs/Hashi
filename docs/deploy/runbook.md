# Deploying hashi

## Короткая памятка

Команды выполнять из каталога проекта на сервере панели, если не указано другое.
`make` — от владельца каталога, без `sudo`; `ufw`, `sysctl`, `systemctl` — через `sudo`.

### Развернуть панель

1. Установить Docker с Compose, Make, Bash и `amneziawg-tools`.
2. Доставить код со своего компьютера (репозиторий закрытый, на сервере нет доступа к нему):
   ```bash
   ssh -t USER@SERVER 'sudo install -d -o USER -g USER /opt/hashi-control'
   git archive HEAD | ssh USER@SERVER 'tar -x -C /opt/hashi-control'
   ```
   Обновление кода — та же вторая строка.
3. Скопировать `.env.example` в `.env`; заполнить домены, параметры БД,
   `HASHI_SECRET_KEY` и хеш пароля (`make hash-password`). Секретный ключ
   сгенерировать на своём компьютере и сохранить отдельно от сервера и бэкапов.
4. Направить DNS домена на сервер; открыть SSH и порты HTTP/HTTPS.
5. Выполнить `HASHI_MGMT_CONFIGS_TO=~/mgmt-devices make panel-bootstrap`. Он же создаёт
   управляющий туннель (если заполнены `HASHI_MGMT_*`) и в конце печатает строки
   `sudo …`, чтобы поднять туннель и сохранить его после перезагрузки. Выполнить их
   как напечатано. Конфиги устройств забрать из `~/mgmt-devices` и удалить там.
   Затем `HASHI_PRIVATE_BIND_ADDR` в `.env` = адрес туннеля и `make up-panel`.
   Без туннеля — `make up-panel-over-ssh`.

### Открыть панель

Через управляющий туннель либо SSH с вашего компьютера:

```bash
ssh -L PORT:127.0.0.1:PORT USER@SERVER
```

Через туннель открыть `https://PRIVATE_HOST:PORT/panel/`, через SSH —
`https://127.0.0.1:PORT/panel/` (Caddy отвечает консолью и на этом адресе);
значения взять из `HASHI_PRIVATE_HOST` и `HASHI_PRIVATE_PORT`.
На публичном домене `/panel/` отвечает **404 — это нормально**.

### Добавить ноду

1. Подготовить сервер с компьютера, где есть проект:
   ```bash
   make node-bootstrap NODE=USER@HOST \
     ARGS="--authorized-key '<публичный SSH-ключ панели>' --port <порт>/udp"
   ```
   Для TCP-протокола указать `/tcp`; добавить `--port` для каждого нужного порта.
   Сервер панели, если он же нода, готовить так же, с `--user <аккаунт>`.
2. **Nodes → Add node**: адрес, SSH-пользователь из результата bootstrap,
   SSH-порт и приватный SSH-ключ.
3. Включить транспорт и нажать **Apply**.
4. Для отдельного входа и выхода: **Hops**, связать entry → leaf;
   затем **Apply** обеих нод. Entry с hop требует resolver;
   пользовательский транспорт — обычно `vless-reality`, hop — `amneziawg`.
   Без hop можно использовать `amneziawg` для пользователей.

### Добавить или отключить человека

- **Добавить:** **Users → Add user** (можно несколько имён, по одному в строке).
  Панель сама применяет изменения на нодах, где у человека появился доступ, и
  показывает результат по каждой: ✓ — готово, ✗ — причина и кнопка **retry**.
  Затем передать ссылку. Для AmneziaWG скачать архив по ссылке конфигурации,
  распаковать и импортировать `.conf`.
- **Из Telegram:** если бот включён (раздел *Adding a user from Telegram*, ниже), написать
  ему `/adduser <имя>` (несколько — по одному в строке); ответом придут те же ссылки, что
  показывает панель. `/nodes` — какие ноды отстают (тот же блок **NOT APPLIED**), под
  каждой готовая строка `apply it: /apply <имя ноды>`; `/apply <имя ноды>` — та же кнопка
  **Apply** с экрана Nodes для одной ноды: она вводит ноду в строй (draft или degraded),
  поэтому сначала `/nodes`. Отзыв и повторный показ ссылки — только в панели.
- **Отключить:** **Users → revoke** → подтвердить. Изменения применяются на
  нодах сразу и сами. Вернуть доступ — добавить под **новым** именем (старое
  занято, панель откажет) и выдать новую ссылку.

### Где смотреть

- **Overview** — общее состояние и бэкапы.
- **Nodes** — состояние нод, ошибки и неприменённые изменения.
- **Users** — доступ и ссылки; **Hops** — связи; **Audit** — действия администратора.
- `make ps` — контейнеры панели; `make logs` — ошибки.
- На ноде: `cd /opt/hashi && docker compose ps`.

### Бэкапы

Настроить `HASHI_BACKUP_*` в `.env`, затем:

```bash
make backup             # сделать сейчас
make backup-schedule    # включить расписание
make backup-status      # проверить результат
```

Отдельно сохранить **исходный `HASHI_SECRET_KEY`**, приватный ключ **age**
и доступ **на чтение** S3. `.env` в бэкап не входит.

### Восстановить из файла

В `.env` должен стоять исходный `HASHI_SECRET_KEY`.
**Восстановление заменяет текущую БД:**

```bash
HASHI_RESTORE_AGE_IDENTITY=/path/to/age-key.txt \
  make restore FROM=backups/hashi-<дата>.sql.gz.age
```

Команда сама перезапускает панель. После — проверить **Users** и **Nodes**.

### Восстановить после потери сервера

Если потерян сервер, где стоят панель и первый хоп (entry), — со своего компьютера,
из каталога проекта:

1. **Переключить DNS** `HASHI_PUBLIC_HOST` (и имя, по которому пользователи
   подключаются к entry) на новый сервер.
2. **Панель:**
   ```bash
   make restore-panel HOST=root@НОВЫЙ_IP
   ```
   Берёт `secrets/server.env`, `secrets/restore.env` и
   `secrets/hashi-backup-identity.txt` (другие пути: `SERVER_ENV=`, `RESTORE_ENV=`,
   `IDENTITY=`). Сам ставит Docker, Make, cron, выключает логирование `ufw`,
   доставляет код, кладёт `.env`, восстанавливает последний бэкап из бакета, ждёт,
   пока DNS укажет на сервер, публикует панель и возвращает расписание бэкапов.
   Ключ age лежит на сервере только во время восстановления и затем удаляется
   (`shred`), в том числе при ошибке. В конце печатает строку `ssh -L …` и адрес
   консоли `https://127.0.0.1:PORT/panel/`.
3. **Первый хоп:**
   ```bash
   make restore-node NODE=<имя ноды> HOST=root@НОВЫЙ_IP
   ```
   Читает запись ноды из восстановленной панели, создаёт на сервере аккаунт
   `hashi` (другой — `ACCOUNT=`), ставит ключ панели, открывает порты ноды
   и порты Caddy, если панель на том же сервере. Затем переносит запись ноды на
   новый сервер (запись в **Audit**) и применяет конфигурацию. Если панель на
   другом сервере, добавить `PANEL=root@IP_ПАНЕЛИ`.

Обе команды можно запускать повторно. Если DNS ещё не обновился, панель уже
восстановлена: дождаться DNS и запустить ту же команду ещё раз, второй раз бэкап
не восстанавливается. Ссылки пользователей не меняются, если они используют имена
и ключи остались прежними. Управляющий туннель создаётся заново отдельно, и
команда `restore-panel` подсказывает как.

Только сама панель, без нод (вручную, на новом сервере, после установки
зависимостей, доставки кода и заполнения `.env` с **исходным `HASHI_SECRET_KEY`**):

```bash
set -a; . /path/to/restore.env; set +a
HASHI_RESTORE_AGE_IDENTITY=/path/to/age-key.txt make restore-from-bucket
```

**Главное:** добавление и отзыв людей применяются сами. **Apply** вручную нужен
после изменения настроек транспорта, маскировки или резолвера: панель
показывает это блоком **NOT APPLIED** с кнопкой. После повторного
`panel-bootstrap` снова выполнять `up-panel` или `up-panel-over-ssh`.
Для добавления и удаления устройств управляющего туннеля менять список в `.env`,
выполнять `make mgmt-tunnel`, затем `sudo systemctl reload awg-quick@awg-mgmt`.

---

**WHAT:** the commands to bring hashi up on real hosts — one installation procedure,
whichever machines the three roles end up on — and the traps that are known, named and
not yet fixed.

**WHY:** the repository proves that the code holds together. It does not tell you which
machines to rent, which port each thing wants, or which two of those wants collide. This
file is that, and it is written to be followed at 3am from a phone tether.

**HOW:** decide where the three roles go, run the shared preparation once, then follow
*Installing hashi* from the top. The arrangement you chose changes which box you type
each step on and which values you put in a node record; it never changes the steps, and
no step asks you which arrangement you built. Every command below is idempotent —
re-running is always safe.

---

## Where the three roles go

hashi has three roles: the **control plane** (**C** — the database, the panel and the
endpoint a user's app refreshes its subscription from), an **entry** node (**E** — what a
user's device dials) and a **leaf** node (**L** — where a user's traffic leaves for the
internet, reached from the entry over a hop). They go on one, two or three machines in any
combination, and none of them is a setting: the arrangement is wherever you ran each
step.

| Machines | Arrangement | Who answers a user's refresh | Where `HASHI_SECRET_KEY` lives | Who holds TCP 443 |
|---|---|---|---|---|
| 1 | **C+E+L** — one box, no hop | the control plane, on `HASHI_PUBLIC_HOST` | on that box | the control plane's Caddy, so a user-facing transport goes on another port |
| 2 | **C+E \| L** — control plane on the entry | the control plane, on `HASHI_PUBLIC_HOST` — which is the entry's own box | on the entry | the control plane's Caddy, on the entry |
| 2 | **C+L \| E** — control plane on the leaf | the control plane; **and** the entry, for its own users, once it is a delivery host (*Which host answers a refresh*, below) | abroad, with the leaf | the control plane's Caddy on C+L; on E, the delivery listener once it is one |
| 3 | **C \| E \| L** | as for C+L \| E | on C | as for C+L \| E |

**What each one costs is in that table and nowhere else in the procedure.** Put the
control plane on the entry and the key that decrypts every credential sits on the machine
most likely to be seized, beside the database it opens — the charter's own condition for
putting the panel inside Russia is a key that does *not* live on that host, and
`panel-bootstrap.sh` requires it in that host's env file, so that arrangement violates the
condition and is run knowingly or not at all. Put the control plane abroad and the
key is out of reach, but its own refresh URL is behind the border at the moment a
whitelist shutdown makes a user need it — which is the gap a delivery host exists to
close, for as long as the certificate it holds lasts.

**A one-box install is the right first run.** It is the cheapest way to find out whether
the images start, the SSH push works and a client accepts the link. Growing from it to the
charter's topology has a section of its own — *Growing out of one box*, below — because the
obvious way to grow it, making the box you have the entry, is the way that destroys every
credential your users are connecting on today.

None of these proves the charter's first success criterion. "Survives a mobile whitelist
shutdown" is a field observation on a real Russian network, made with your own phone. No
test in this repository claims it and none ever will.

---

## Before you install

### On your own machine

```bash
git clone <this repo> hashi && cd hashi
make setup                                        # needs Python 3.14
make verify                                       # the gate: static zones + tests/e2e

python -c "import secrets; print(secrets.token_urlsafe(48))"   # → HASHI_SECRET_KEY
.venv/bin/python -m control.cli hash-password                  # → HASHI_OPERATOR_PASSWORD_HASH

ssh-keygen -t ed25519 -f ~/.ssh/hashi-node -C hashi-control -N ''
```

`make verify` is the one command that answers "is this green": it runs the three static
zones, boots the disposable e2e stack, runs `tests/e2e/` against it and tears it down. It
needs a docker engine and **fails** without one rather than skipping — `make test` is the
static half, and a smaller claim. Neither says anything about whether a tunnel carries
traffic on a Russian network; nothing in this repository does.

Both secrets are generated here and nowhere else, and that is not a style preference:

- `hash-password` prompts instead of taking an argument, so the plaintext never enters
  your shell history or `/proc`. Minimum 12 characters, enforced — and there is **no
  lockout on failed logins** (a deliberate decision in `control/app/auth.py`: with one
  operator, a lockout is a denial-of-service against the one person who needs the panel
  during an emergency). Length is the whole defence. Use far more than twelve.
- `panel-bootstrap.sh` **refuses to generate `HASHI_SECRET_KEY` on the host it
  installs.** That key decrypts every user's credential and every node's private key.
  If the panel sits on the Russian entry node, a key generated there would live on the
  machine most likely to be seized, beside the data it opens.

Keep a copy of `HASHI_SECRET_KEY` somewhere that is not the control host and not the
backup directory. **A dump without the key restores nothing**, and both in one place
defeats the encryption.

### DNS

Point an **A record** for your panel hostname at the control-plane box *before* you
publish it. Caddy asks a public CA for the delivery name's certificate the moment
`make up-panel` (or `make up-panel-over-ssh`) publishes 80 and 443, and a name that does
not resolve to that box then fails validation over and over — and every failure counts
against that name's issuance rate limit.

**Not before.** The stack `make panel-bootstrap` and `make restore-from-bucket` bring up
publishes nothing, so no CA could validate it, and it asks none: it serves the delivery
name from Caddy's own CA until a publishing command switches public issuance on
(`HASHI_PUBLIC_TLS`, set by `deploy/docker-compose.public.yml` and by nothing else — M31.1).
Until M31 it asked anyway, from the first boot, and a restore walk found the ACME accounts
and a challenge token already on a host whose ports were closed.

### What every box must already have

**A node:** docker, and SSH. That is the entire list — **hashi does not install a
container runtime for you** when it drives a node; it runs `docker version`, and if that
fails it stops and says so (`edge/bootstrap/node_stack.py`). You do not need to collect
SSH host keys: the first successful connect learns the node's host key and pins it from
then on, so a later connection cannot be silently intercepted.

**The control-plane box needs five more things, and a genuinely bare one may have none of
them:** a container runtime with the compose plugin; `make`, because every command in the
block below is a Make target; `bash`, because every script those targets run is a bash
script; `amneziawg-tools` — with the AmneziaWG kernel module or `amneziawg-go` for it to
drive — because the management tunnel the console is reached over is an `awg-quick@` unit
from that package (*Bringing it up, and keeping it up across a reboot*, below); and `git`
**only if** the box is to fetch the code itself with a deploy key — shipped from your own
machine as *Ship the code to the control-plane box* shows, it needs none. An acceptance
walk on a bare host found the runtime, `git` and `make` missing and the runbook listing
none of them; the restore walk of 2026-10-02 met a minimal image without `bash`, and
`make restore-from-bucket` died on `env: can't execute 'bash'` before any of its own
checks could speak. Every such target now asks for bash first and says so in a sentence
(M31.7), but install it with the others: `apt-get install bash`, `apk add bash`.

**Which boxes need `amneziawg-tools`:** the control plane's box, whatever else it carries,
whenever it is to have a management tunnel — and no other. A node's AmneziaWG runs from
the container image the control plane pushes (`edge/bootstrap/node_stack.py`), so a box
that is only a node needs nothing of it.

**The runtime goes on the control-plane box by hand, before its block**, and the account
that will own the checkout goes in the `docker` group — on a box that is also a node too,
because the control plane comes up before that box is prepared as a node:

```bash
curl -fsSL https://get.docker.com | sudo sh && sudo docker version
sudo usermod -aG docker ACCOUNT      # then log in again, so the group applies
```

**On a node, install nothing else by hand and authorise no key by hand — the control
plane's own box included, when it is also a node.** `scripts/node-bootstrap.sh` installs
the runtime where there is none (and leaves one that is there alone), authorises the
control plane's key and brings the firewall up in one run that asks no questions, and
running it again changes nothing — see *Preparing a node* below. A control-plane box that
is **not** a node has no key to authorise at all: nothing dials it over SSH.

### The env file

On the control-plane box, `cp .env.example .env` and fill in:

| Key | Note |
|---|---|
| `HASHI_SECRET_KEY` | from your machine; never generated on the host |
| `HASHI_PUBLIC_HOST` | the panel/delivery hostname, already pointing here |
| `HASHI_OPERATOR_USERNAME` | `owner` is the default and is guessable — that is fine, the password is the defence |
| `HASHI_OPERATOR_PASSWORD_HASH` | the hash, never the password. `make hash-password` produces it **on this host**, inside the control image, with nothing installed but the container runtime; `python -m control.cli hash-password` is the same command on a machine that already has the project set up |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `HASHI_DATABASE_URL` is composed from these, so the app and the database cannot drift apart |
| `CADDY_ACME_EMAIL` | not checked by the bootstrap script; compose fails without it |
| `HASHI_PRIVATE_HOST` | the name your own devices ask for over the management tunnel — usually this host's tunnel address |
| `HASHI_PRIVATE_PORT` | where Caddy serves the console; the same variable drives the listener and the published mapping, so they cannot drift |
| `HASHI_PRIVATE_BIND_ADDR` | which address on **this** host the console is published on. The tunnel's, never loopback — see *Reaching the panel*. Read only by `make up-panel`; a host with no tunnel yet leaves it unset and publishes with `make up-panel-over-ssh` |
| `HASHI_MGMT_*` | optional: the management tunnel's own address, port, endpoint, MTU and device list. Absent means no tunnel is generated |
| `HASHI_DELIVERY_CERTIFICATE_PATH` / `HASHI_DELIVERY_KEY_PATH` | optional, and blank is the default: no node answers refreshes of its own. Set only when an entry that is not this box should — *The delivery certificate*, below |

**Paste the hash exactly as `hash-password` printed it, doubled `$$` and all.** The
command now prints `scrypt$$32768$$8$$1$$…` rather than `scrypt$32768$8$1$…`, and the
doubling belongs in the file: `docker compose --env-file` interpolates the values it
reads, turns each `$$` back into one `$`, and would read a single `$<salt>` as a variable
name and replace it with nothing. Whether that destroys the hash depends on the salt's
first byte — one starting with a letter is silently eaten, one starting with a digit
survives — so the same procedure worked on one host and locked the owner out of the next,
with "Those credentials were not accepted" beside a hash that looked perfectly correct.
**Do not double them a second time.** If you are working from a hash generated before this
changed, double it once by hand. Two things now catch the mistake either way: the
bootstrap script refuses an env file with a lone `$` (it will not rewrite a file full of
your secrets), and the control plane refuses to start on a hash that is not one, rather
than serving a login nobody can pass.

### The port-publication gap

`deploy/docker-compose.yml` publishes **no ports at all**, on purpose, and no overlay can
take a published port back — `ports:` is a sequence and the Compose spec merges sequences
by appending, so a `443:443` in the base file would follow every `make up-dev` and every
`make e2e-up` onto your laptop.

So `panel-bootstrap.sh` installs a stack that nothing outside the host can reach, and it
says so: it verifies the control plane from *inside* the compose network and ends by
naming what it proved and what it did not. It used to end with `The panel is at
https://…/panel/` — an address that answered nothing, because 80 and 443 were closed. It
prints no address now. Publishing is still a separate, deliberate step, and there are two
of them because a host either has a management tunnel or does not:

```bash
make up-panel            # the delivery endpoint, and the console on this host's
                         # management-tunnel address
make up-panel-over-ssh   # the same without that last mapping, for a host with no tunnel
                         # yet: the console answers on loopback only, reached with ssh -L
```

That is the base stack plus `deploy/docker-compose.public.yml` — and, for the first,
`deploy/docker-compose.tunnel.yml` on top. Both **ship with the repository**: they used to
be a heredoc you typed onto the box, and that stopped being survivable when the file grew
a mapping whose bind address is the difference between a private console and a public one.
Caddy only. Never the database.

**Why two files.** `HASHI_PRIVATE_BIND_ADDR` is the one value in the deployed shape that
names an address *this host must actually hold*, and a machine restored from a bucket
holds no tunnel address — the tunnel's keys were on the box that was lost. `make up-panel`
there fails on a bind docker cannot make, at the point where the operator cannot log in
yet; the bare-host walk of 2026-09-23 answered it with `ip addr add`, by hand. So the
mapping that needs a tunnel is a file of its own, and everything a deployed host publishes
regardless — including the loopback fallback the `ssh -L` route uses — is in the other.
Neither publishes the console on an address the internet can reach.

**And remember it after every `make panel-bootstrap`.** That script uses the base file
alone, on purpose — so a later run brings the stack back to the base file's shape and
takes the published ports away again. Run `make up-panel` afterwards, or run it instead
of the script once the box is installed. **The script says this itself now**, before it
converges and again when it has finished, and only on a host that was in fact publishing
something: it asks the running stack what it publishes rather than guessing. It is said
there because "a second run is safe" is printed by every refusal in the restore path, and
the one thing a second run is not safe for was written down only here — under a heading
an operator re-running a command has no reason to open.

---

## Reaching the panel

**The console is not on your public hostname.** As of M7 Caddy serves two sites out of
one container:

| site | serves | reachable from |
|---|---|---|
| public — `HASHI_PUBLIC_HOST` on 80/443 | `/sub/*`, and a redirect to https | anywhere, which is the point: a user refreshes their config from inside Russia at the moment a node was blocked |
| private — `HASHI_PRIVATE_HOST` on `HASHI_PRIVATE_PORT` | `/panel/*`, `/api/*`, `/static/*` | the management tunnel, and loopback |

Everything a site does not serve is `404`, with no body and nothing that says the other
site exists. The console holds every node key and every user credential, and there is
deliberately **no lockout on repeated failed logins** (`control/app/auth.py`, and it is a
recorded decision rather than an oversight) — so on a public address, password length was
the entire defence. This is what replaces it.

The console's certificate comes from Caddy's own CA, not from a public one: the private
site has no public name and no public address, so ACME could never validate it, and
nothing about the console's existence reaches a CA's logs. Your browser will ask about it
once.

**Set `HASHI_PRIVATE_HOST` to the tunnel address, not to a name**, unless you can resolve
that name on *every* device you would reach the console from — including your phone,
which cannot be given a hosts entry and is the device you reach for in an emergency. This
matters more than it looks: **a TLS client sends no SNI when the host is an IP literal**,
which is true of curl and of every browser, so a console dialled by address tells Caddy
nothing about which certificate it wants. `deploy/caddy/Caddyfile` answers that with
`default_sni`, set to this value — which is why it has to be the address you actually
type. Without it the handshake is aborted with `tlsv1 alert internal error` and the
console is unreachable by both of its routes; that is not hypothetical, it is how this
milestone failed on its first real host.

Two consequences worth knowing, neither of them a reason to change the value:

- `default_sni` is global — Caddy has no per-site form of it — so a client that connects
  to the **public** port without SNI is also answered with the console's certificate, and
  learns this address. It is private and unroutable, and the alternative was a
  certificate-name mismatch on every visit to your own console, which teaches you to
  click through TLS warnings on the one surface that must never be impersonated.
- **`HASHI_PUBLIC_HOST` must be a name with a real DNS record, never a bare address.** A
  public CA cannot issue for an IP, so Caddy falls back to its own CA and every stock
  client refuses the certificate — `/sub/{token}` then fails for every user while
  nothing on the host looks wrong. That is a fact about certificates rather than about
  SNI, and no setting here repairs it.

### The management tunnel

A dedicated **AmneziaWG** tunnel, not plain WireGuard and not a third-party mesh
(`docs/decisions.md`, 2026-09-09 — decision 2 was taken, reaffirmed on measurement, and
then reversed the same day; the sequence is the record). Two things it is not, both
deliberate: it is not a `node_transports` row, because that shape carries one peer
address and therefore serves one device, and you have a laptop and a phone; and it renders
no `PostUp`, no `PostDown` and no `Table`, because it carries traffic **to** this host
rather than **through** it, and forwarding rules would quietly turn your admin tunnel into
an exit.

Fill in the `HASHI_MGMT_*` keys **with this deployment's own values** and run the
bootstrap. It hands out one config per device, **once**:

```bash
make panel-bootstrap
```

On a host that is **already installed and serving**, switch the tunnel on with
`make mgmt-tunnel` instead: the same generator and the same device configs, and no container is
touched, so delivery stays up (see "Adding or removing a device" for what the bootstrap
costs such a host).

You will see `generating the management tunnel the panel is reached over`, then, for each
device, `Its configuration follows ONCE and is not stored anywhere` followed by the file
itself. **Copy each one to its device before you close that terminal.** Nothing stores it:
the private half of a device's key exists in that scrollback and on the device, and
nowhere else. A device whose config was lost gets a new entry in `HASHI_MGMT_PEERS` and a
new key — a re-run says `already a peer of this tunnel` and prints nothing, because there
is nothing left to print.

**Over SSH, prefer a file per device to the scrollback.** The configs arrive in the same
stream as every progress line, and a phone wants a file or a QR code rather than text
selected out of a terminal. Name a directory for this one run and each new device's config
is written there instead — `0600`, one file per device, and never into the checkout:

```bash
HASHI_MGMT_CONFIGS_TO=~/mgmt-devices make panel-bootstrap
```

Then, from your laptop (both tools are yours, not the project's: `qrencode` from your
package manager, and the AmneziaWG app on the phone imports from a QR code or a file):

```bash
scp 'USER@THE_PANEL_HOST:mgmt-devices/*.conf' .     # the laptop's own goes into its client
qrencode -t ansiutf8 < phone.conf                   # scan it with the phone's AmneziaWG app
rm phone.conf laptop.conf
ssh USER@THE_PANEL_HOST 'rm -r ~/mgmt-devices'
```

That directory is the hand-over, exactly as the scrollback was, and deleting it is yours:
the script never reads such a file back and refuses to overwrite one that is still there,
so a config nobody has moved yet is never silently replaced. Every byte of a device config
is ASCII on purpose — a QR decoder read the em dash an earlier version put in its first
comment as something else.

**Left as `.env.example` ships them, those keys generate nothing**, and that is deliberate:
the template's block is a complete one, so a machine rebuilt by copying that file used to
get a tunnel and two printed private keys for devices nobody owns, aimed at the template's
example endpoint. The bootstrap compares the block against `.env.example`'s own line, skips
the generation and says which mode it left the host in — which for a freshly restored host
is the SSH fallback below.

#### Bringing it up, and keeping it up across a reboot

The run ends with `NOT done, and not yet true: the tunnel is not up and this host is not
listening.` That is accurate: it wrote a file and printed text. Bringing the tunnel up is
yours, as root, and needs `amneziawg-tools` on the host. **The run prints these lines with
this host's real path in them — copy them from there**, not from here: `~` in a root shell
is `/root`, not the home of the user who ran the bootstrap, and an earlier version of this
page said `awg-quick up ~/.hashi/...` and pointed at a file that did not exist.

```bash
sudo install -d -m 700 /etc/amnezia/amneziawg
sudo ln -sfn /home/<bootstrap user>/.hashi/management/awg-mgmt.conf /etc/amnezia/amneziawg/awg-mgmt.conf
sudo ufw allow <HASHI_MGMT_PORT>/udp
echo 'net.ipv4.ip_nonlocal_bind = 1' | sudo tee /etc/sysctl.d/60-hashi-mgmt.conf
sudo sysctl --system
sudo systemctl enable --now awg-quick@awg-mgmt
```

What each line is for, because each one was missing on the first real host:

- **The symlink and the unit.** `awg-quick@` ships with `amneziawg-tools` and reads
  `/etc/amnezia/amneziawg/<name>.conf`. Linking rather than copying keeps one file: every
  later run of the tunnel step changes the file the unit reads, and nothing has to be
  copied again. `enable` is what brings the tunnel back after a reboot — `awg-quick up` by
  hand does not survive one.
- **`ip_nonlocal_bind`.** `make up-panel` publishes the console on the tunnel's address,
  and docker refuses to bind an address the host does not hold. Without this line a
  tunnel that is late or broken at boot — a reboot, a kernel upgrade the AmneziaWG module
  was not rebuilt for — fails **the whole Caddy container**, and the public delivery
  endpoint goes down with the console. That happened on the real host. With it, docker
  binds the address before it exists, Caddy starts, delivery is served, and the console
  answers on the tunnel the moment the interface comes up. It lets any process on the
  host bind an address it does not hold yet, which is the whole of its cost
  (`docs/decisions.md`, 2026-10-03). On an IPv6 tunnel the run prints the
  `net.ipv6.` form instead.
- A drop-in that orders docker after the tunnel (`Wants=`/`After=awg-quick@awg-mgmt` in
  `/etc/systemd/system/docker.service.d/`) is **not needed** with the line above. It is
  harmless if you already have one; it does not replace `ip_nonlocal_bind`, because
  ordering does nothing for a tunnel that fails to come up at all.

**If the interface is already up from an earlier `awg-quick up <file>` by hand**, the unit
cannot start over it: `sudo awg-quick down <that same file>` first, then `enable --now`.
And check there is exactly one management interface — `ip -brief link | grep awg` lists
one `awg-mgmt` line and no other you cannot account for; a second interface answering on
the same address is not a state to leave a host in.

Set `HASHI_PRIVATE_BIND_ADDR` to the tunnel address the interface now holds — that
publication is the whole of "the console is off the public internet", because Caddy inside
the container listens on every interface it has and the host decides which one the port
appears on. Then `make up-panel`, and open the console from a device on the tunnel.

**Never `HASHI_PRIVATE_BIND_ADDR=127.0.0.1`.** Loopback is already claimed for that port
by the fallback below, and docker refuses the second bind with "port is already
allocated"; `panel-bootstrap.sh` checks for it and says so, because that error names
neither the cause nor the cure. **And never an address this host does not hold, without
the `ip_nonlocal_bind` line above** — that is the same mistake wearing different clothes,
and it is what a freshly restored machine has: no tunnel, therefore no address, therefore
`make up-panel` fails on the bind. Leave the variable unset and publish with
`make up-panel-over-ssh` until the tunnel is up.

#### Adding or removing a device

Edit `HASHI_MGMT_PEERS` — one entry more, or one fewer — and run the tunnel step on its
own:

```bash
make mgmt-tunnel                                          # or, for a new device's file:
HASHI_MGMT_CONFIGS_TO=~/mgmt-devices make mgmt-tunnel
```

**Not `make panel-bootstrap`.** That is an install, and on a host that is already serving
it converges the stack to the base compose file on its way to the tunnel step: Caddy loses
80/443 and the console, and every user's `/sub/` link answers "connection refused" until
`make up-panel` — which is what happened on the real host the first time a device was
added this way. `make mgmt-tunnel` runs the same generator and touches no container.

The host file is **converged** to the list: a new name gets a peer and its config, handed out
once; a name you deleted loses its peer, and the run says `removed <name>`; every other
device keeps its keys and stays connected. Then load the change into the running
interface — it is `awg syncconf` underneath, so nobody else's session drops:

```bash
sudo systemctl reload awg-quick@awg-mgmt
```

Until that reload a removed device **still has access**, because the running interface
still holds its peer. A device's name is how it is matched on every later run, so
**moving a device to another address is a new name**, not an edit: write
`phone2=<new address>` in place of `phone=<old address>`, and the run removes the old peer
and hands out a new config in one go. Editing the address under the same name is refused
and changes nothing.

#### Starting the tunnel over

`HASHI_MGMT_ADDRESS`, `HASHI_MGMT_PORT` and `HASHI_MGMT_MTU` are inside every device
config already handed out, so the tunnel step **refuses** to keep a host file that disagrees
with them — it names each key with both values and changes nothing. `make panel-bootstrap`
runs that refusal before it touches the stack, so there too a refused run has taken nothing
off the air. (An earlier version
kept the old file and said so in a line that read like success, and the first new device
then collided with an old one's address.) Either put the old values back, or retire the
host end and start over:

```bash
sudo systemctl disable --now awg-quick@awg-mgmt
mv ~/.hashi/management/awg-mgmt.conf ~/.hashi/management/awg-mgmt.conf.retired-$(date +%Y%m%d)
sudo ufw delete allow <the OLD HASHI_MGMT_PORT>/udp     # if the port changed
make mgmt-tunnel                                         # with the new values in .env
sudo systemctl enable --now awg-quick@awg-mgmt
```

(the `mv` runs as the bootstrap user, so `~` is right there). **Remove the old port's
firewall rule** whenever the port changes — a rule for a port nothing listens on any more
is an opening nobody remembers the reason for. Every device then needs its **new** config,
and its old tunnel should be deleted from it. If the tunnel address changed, change
`HASHI_PRIVATE_BIND_ADDR` and `HASHI_PRIVATE_HOST` to match and `make up-panel` again. The
retired file still holds the old private key; delete it once the new tunnel works.
`HASHI_MGMT_ENDPOINT` is not in the host file, so changing it is not refused — but every
device already handed a config still dials the old one. Give each device a new name in
`HASHI_MGMT_PEERS` (the run removes the old peers and hands out new configs), or retire
the host end as above.

### The way back in when the tunnel is unavailable

**This route is tested, not merely described**, and the difference matters: the day you
need it is the day of an emergency rotation, and a fallback nobody has run is a paragraph.
It is also the route this project's own field run used all night.

`make up-panel` publishes the console's port a second time, on this host's loopback only
— and `make up-panel-over-ssh` publishes *only* that one, which is the whole of its
difference. Nothing off the host can reach it; anything that can already open an SSH
session can forward it:

```bash
ssh -L PRIVATE_PORT:127.0.0.1:PRIVATE_PORT USER@THE_PANEL_HOST
```

Then, on your own machine, open `https://127.0.0.1:PRIVATE_PORT/panel/` — the same
console, the same certificate, the same login. The site block answers to the loopback name
as well as to the tunnel name precisely so that this arrives somewhere rather than at a
`404`.

Check it now, while nothing is on fire, and check it again after any change to the panel
host. One command, from your own machine, with the forward open:

```bash
curl -k -o /dev/null -w "%{http_code}\n" https://127.0.0.1:PRIVATE_PORT/panel/login
```

`200` means the way back in works. Anything else means it does not, and you have found
that out on a quiet afternoon instead of during a rotation.

**What this cannot tell you.** Your machine and the panel host may share a cloud region,
in which case traffic between them never traverses ТСПУ and an uninterrupted SSH session
says nothing about your home or mobile network. Only you can test that, from the network
you would actually be on.

---

## Preparing a node

A rented host, an SSH session, and ten minutes. This section is **every** node — the leaf
abroad, the entry in Russia, and the control plane's own box when it is also a node — because
they are all prepared the same way: **one script, `scripts/node-bootstrap.sh`, and nothing by
hand.** A hand-prepared host is a host you cannot rebuild at three in the morning, which
is precisely when you rebuild one.

It gives the host four things and stops: a container runtime, the one **public** key the
control plane authenticates with, the host firewall — with logging off before the firewall
ever comes up — and one **empty** directory, `/opt/hashi`, owned by the account you will
register. It installs **no hashi code and no hashi state**: everything that ever lands in
that directory is rendered by the control plane and pushed over SSH on your first apply. An
empty directory is not state — nothing in it needs regenerating, because nothing is in it —
and why it is created here rather than by the control plane is *Which accounts work*, below.

### Run it

From the machine that holds this repository and the key pair, so that nothing of the
repository lands on the node:

```bash
make node-bootstrap NODE=USER@THE_NEW_HOST \
  ARGS="--authorized-key '$(cat ~/.ssh/hashi-node.pub)' --port TRANSPORT_PORT/udp"
```

**The words in capitals are the placeholders**, and they are capitals rather than
`<angle brackets>` for one reason: a shell reads an angle bracket as a redirection, so a
line pasted with the brackets still in it dies on a message that names neither this script
nor the thing you forgot to fill in. Substitute all of them — none has a default.

That is `ssh THE_NEW_HOST 'bash -s -- ARGS' < scripts/node-bootstrap.sh`: the script is
piped in and never copied, which is what keeps repository code off a node. Add
`SSH_PORT=THE_PORT` if the host does not answer on the default one. If you are already
sitting on the host, run `./scripts/node-bootstrap.sh` with the same arguments.

| Argument | |
|---|---|
| `--authorized-key TEXT` | the **public** half of the pair you generated on your own machine. `--authorized-key-file <path>` reads it from a file already on the host. |
| `--port PORT[/PROTO]` | repeatable, one per transport this node will run — the same number you will enter in the node record. |
| `--user NAME` | the account the control plane logs in as; defaults to the invoking account (or `SUDO_USER` under sudo). |
| `--ssh-port N` | only when the script cannot work the management port out for itself. |

Progress lines start `==> `. A refusal exits **1** and starts `node-bootstrap: `; an
argument it does not recognise exits **2** and prints the usage. **Both of those are the
script's own codes, and `make` does not pass them on**: GNU make exits **2** whenever a
recipe fails, whatever the recipe returned, so through `make node-bootstrap` a refusal and
a typo are the same number. Read the sentence rather than the code — that is what the
sentence is for — or run the `ssh … < scripts/node-bootstrap.sh` line above directly, where
the codes are the script's. It refuses rather than
guessing, and these are the refusals worth knowing about before you start — each one is a
mistake you want stopped here rather than found on a node that says it is ready:

- **No key, or a key that is not a public key.** The private half belongs in the node
  record, encrypted, and never on a node — a key generated or pasted on the host would sit
  in clear on the machine most likely to be seized. Generate the pair where the control
  plane lives (*Before you install*, above) and pass the `.pub` half.
- **More than one key.** `authorized_keys` holds one key per line, so a value with a
  newline in it authorises *every* line in it for that account — including one you did not
  read. `--authorized-key-file` reads the whole file for the same reason: it used to take
  the first line and say nothing about the rest. Pass the one key the control plane
  authenticates with; if the file you are copying from holds several, choose there. This
  one is refused **before anything is installed**, so the host is untouched and the run is
  safe to repeat.
- **An argument that is not a port.** `--port` and `--ssh-port` are both checked on the
  command line, before the host is touched at all — a typo costs you a re-run and not a
  half-prepared node.
- **It cannot tell which port sshd listens on.** It reads the port this session arrived on
  and the ports `sshd -T` reports, and if neither answers it stops rather than enabling a
  firewall it cannot prove leaves you a way back in. Pass `--ssh-port`.
- **The account is not root and sudo wants a password.** The run is piped over SSH and must
  never prompt, so give the account passwordless sudo or run as root.
- **The account does not exist yet.** It authorises a key *for* an account and puts that
  account in the `docker` group; it does not create one. Make it first, name another with
  `--user`, or leave the flag off.
- **sshd on this host will not read the file the key was installed in.** The run asks
  `sshd -T -C user=THE_ACCOUNT` which files the daemon really consults *for that account*,
  because a key in a file sshd never opens is not an authorisation. The shape that does
  this is a host taking its keys from an `AuthorizedKeysCommand` — instance metadata, on
  most cloud providers — with no `AuthorizedKeysFile` beside it. Add the key to whatever feeds that command, or set
  `AuthorizedKeysFile` in `/etc/ssh/sshd_config`, reload sshd, and run this again.
- **sshd reads that file and still will not let this account in with a key.** A different
  sentence from the one above, and the run asks both: `PubkeyAuthentication no` accepts no
  key from that account; an `AuthenticationMethods` list with no alternative that is a key *on
  its own* — `publickey,password`, where the comma means both are required — leaves the
  control plane, which has only a key, half way in; and with the default `ssh_user`,
  `PermitRootLogin no` or `forced-commands-only` keeps that key out of root. Fix the
  directive it names and reload sshd, or prepare another account with `--user` and
  register **that** name. `prohibit-password` is not one of these: it permits a key and
  refuses only a password, which is what a hardened host should have.

  **Both questions are asked about the account you are preparing**, not about the top of
  `sshd_config`: the run hands sshd `-C user=THE_ACCOUNT`, so a `Match User` or `Match
  Group` block that moves this account's keys or switches them back on for it is part of
  the answer. It hands sshd **no address**, which is deliberate and is the limit — a
  `Match Address`, `Match Host`, `Match LocalAddress` or `Match LocalPort` block is not
  seen, because an address in that script would be a piece of node topology the fleet
  could not rotate away from.
- **`net.ipv4.ip_forward` is not 1.** Then the kernel moves no packet from a tunnel out to
  the internet, and every other signal stays green while nothing arrives anywhere. It is 1
  on most hosts only because the docker daemon sets it at every start. Set it, put it in a
  file under `/etc/sysctl.d/` so it survives a reboot, and run this again — the script
  reads that setting and never writes one.

**One thing it names and does not refuse:** strict reverse-path filtering
(`net.ipv4.conf.all.rp_filter` and `net.ipv4.conf.default.rp_filter`, where `1` is strict
and `2` is loose). It is correct on a leaf and it breaks an **entry** node — the replies
coming back over the hop arrive on the hop's interface, the kernel decides they should not
have, and drops them before anything on the host sees them, so the hop handshakes and
carries nothing. The script is not told which role you will register the host in, so it
prints what it found and leaves the decision with you. If this box is going to be the
entry, set both to loose, or off, before you register it.

### Which accounts work

**Root works, and so does any account with passwordless `sudo`.** That is the whole list,
and both halves of the product agree on it — a test fails if they stop.

The control plane logs into a node as exactly the account in the node record and **never
escalates**: no `sudo`, no `su`, nothing per-node to switch on. It is a library that
configures upstream daemons, and giving it a privilege model would give every node one.
That is affordable only because the account already has everything it needs by the time
the control plane first connects, and arranging that is this script's job:

- **it owns `/opt/hashi`**, created here empty and `0700`, because `/opt` is root-owned and
  the account could not create it itself;
- **it is in the `docker` group**, so it can reach the socket the data plane runs on;
- **its `authorized_keys` holds the control plane's public key**, and nothing else
  authenticates.

Pass `--user THE_SSH_USER` when that is not the account you are running the script as, and
register **that** account in the panel — the run's `register it in the panel with ssh_user`
line names the one it prepared. An account the script never saw has none of the three.

**A host prepared before this script existed, or by hand as root, and now driven as a
non-root account** is missing the first of the three. The apply fails with a sentence
naming the directory rather than a `Permission denied` from inside a `mkdir`, and there are
two ways out: run this script against the host, or create the directory once, as root:

```bash
install -d -m 700 -o THE_SSH_USER /opt/hashi
```

**Changing the account of a node that has already been applied to** has its own section
below — *Changing the account a node is driven as*. Re-running this script with the new
`--user` is now enough for the **host** half, and no recursive chown typed by hand is
needed or wanted. The half it cannot do is change which account the control plane dials:
that is `make node-relocate`, in that section — read it before you change the account of a
node that is serving.

### The control plane's own box, when it is also a node

On C+E+L, C+E | L and C+L | E the control plane reaches its own box the way it reaches any
other node — over SSH, out through the box's public address and back in — so that box gets
**the same run as every other node**, with nothing authorised by hand. That is the version
that worked on a from-scratch install; there is no shortcut through the control-plane block
for it. Run it from your own machine like any other:

```bash
make node-bootstrap NODE=ADMIN_ACCOUNT@THIS_BOX \
  ARGS="--user NODE_ACCOUNT --authorized-key '$(cat ~/.ssh/hashi-node.pub)' --port TRANSPORT_PORT/tcp"
```

`ADMIN_ACCOUNT` is whoever can run the script — root, or an account with passwordless
`sudo`. `NODE_ACCOUNT` is the account the control plane will log in as, and the one you
register as `ssh_user`: the run's `register it in the panel` line names it. It needs no
`sudo` of its own — only the three things *Which accounts work* lists, which the run gives
it. **Choose an account other than root** unless you want root logging in by key (M31.10,
from the field walk of 2026-10-02).

**What the firewall this run brings up does to the control plane on the same box** —
measured on the M36 stand (a fresh Ubuntu container with docker and ufw default-deny, 2026-10-13): Caddy's
published ports kept answering from another machine with **no** ufw rule for them, because
docker publishes through its own iptables chains and ufw's INPUT policy never sees that
traffic; a data plane, which runs on the host's network, stopped answering the moment its
rule was removed. So the `--port` that matters on this box is the node's own transport port,
as above. `make restore-node` opens Caddy's published ports as well, read off the running
container, so that the answer does not depend on docker's iptables staying where they are.

### What a finished run says

```
==> created /opt/hashi, empty and owned by <user>
==> sshd reads <the account's ~/.ssh/authorized_keys>, so a key installed there is one it will consult
==> the running firewall was asked and it is not logging
==> ready: docker <version>, key authorised, firewall up, logging off
==> register it in the panel with ssh_user <user> and ssh_port <port>
==> no hashi code and no hashi state was installed here — /opt/hashi is an empty directory owned by <user>, and the control plane fills it on your first apply
```

**Two of those lines are about the same thing said twice, deliberately.** Earlier in the
run the script reports what `/etc/ufw/ufw.conf` says, because while ufw is inactive that
file is the only thing there is to read. It claims the firewall is not logging only after
asking the running firewall, and it refuses if the answer is anything else — the two can
disagree, and a ufw that silently ignores `ufw logging off` is exactly that host. This is
the one record the charter forbids at any level, so the run says what it read rather than
what it assumes.

Take the `ssh_user` and `ssh_port` from the `register it in the panel` line — it names the
port this session actually arrived on, which is the one port known to work from outside. Then, in the panel:
**Add node** with those values and the contents of `~/.ssh/hashi-node` as the private key,
enable the transport on the port you opened, and **Apply**. Nothing before the apply has
told the fleet this host exists: the script writes nothing to the control database, and a
node never dials the control plane.

### Running it on a host somebody already prepared

The normal case, not the exception — both hosts of this project's own field run already
had docker, and one already had an active firewall carrying its own rules. A second run,
or a first run on a host with a past, reports rather than changes:

```
==> docker is already installed — left exactly as it is
==> the control plane's key is already authorised for <user>
==> /etc/ufw/ufw.conf already reads LOGLEVEL=off
==> <port>/<proto> was already open
==> incoming was already denied by default
==> the firewall was already up — its existing rules were kept
==> /opt/hashi was already here — <user> now owns it and everything an earlier apply left inside it; nothing in it was read, changed or removed
==> no hashi code and no hashi state was installed here — /opt/hashi was already here, and the control plane replaces what is in it on your next apply
==> /opt/hashi was already here before this run — whatever an earlier apply left in it, this run neither read, changed nor removed it; it now belongs to <user> along with the directory, so an apply as that account can replace it
```

The closing line is the one from the first-run block above, in the form this run can
honestly make: a host that already has the directory is not told it is empty. Both forms
say the same thing about what the script installed, which is nothing.

Nothing there is a warning. What the script never does is **close** anything: the rule set
is the union of every run, because a script that withdrew a rule could withdraw the one
carrying the session running it. Narrowing a rule set is an operator's job, done knowingly.

### Changing the account a node is driven as

The last two lines above are the whole of it, and they are there because the obvious
reading of this section used to be wrong. A node applied as one account and then handed
to another kept the **files** of the first: `/opt/hashi` belonged to the new account, and
everything an apply had written inside it still belonged to the old one. The next apply
failed on a permission error naming a path — three layers away from the account that
caused it, on a host whose bootstrap had just said `ready`.

So re-running the script with `--user <new account>` now **is** sufficient — **for the
host**. It takes ownership of the directory's contents along with the directory, reading
none of them and removing none of them; the account it prepares can then replace every
file an earlier apply left.

**The control plane's half is a relocation since M36.** A node's `ssh_host`, `ssh_user`
and `ssh_port` used to be written once, at registration, with no way to change them and
no way to reset the pinned host key — so a host handed to a new account and a record still
naming the old one disagreed for ever. Now one audited operation moves the record:

```bash
make node-relocate NAME=NODE_NAME ARGS="--ssh-host NODE_HOST --ssh-user NODE_ACCOUNT --ssh-port SSH_PORT"
make node-apply NAME=NODE_NAME
```

on the control-plane host (or `POST /api/nodes/{id}/relocate`). It records
`<node> moved to a new host` on the **Audit** screen, replaces the pinned host key (pass
`--host-key '<line of /etc/ssh/ssh_host_ed25519_key.pub>'` to pin the new one, or leave it
out and the next apply learns it), and changes nothing on the host — the apply does.
`make restore-node` (the cheat sheet's *Восстановить после потери сервера*) is all of this
plus the bootstrap, for a host that was lost.

`make node-plan NAME=NODE_NAME` prints which account the record names today, so the
disagreement can be read rather than guessed.

### The layer the script cannot see, and the evening it costs

Every run ends on this line, and it is the last one for a reason:

```
==> the provider's own firewall sits in front of this host and outside this script's reach
```

The provider's security group is a **separate layer, in their console, invisible from
inside the host**. `ufw status` on the node tells you nothing about whether a packet ever
reaches the box. And a closed security group looks *exactly* like a broken transport: the
host firewall allows the port, the container is up, every check the script makes is green,
the panel says the node is fine, and the client still times out. An operator who does not
know this layer exists debugs the transport, where there is nothing to find.

**Confirm it from a machine on a different network.** Not from the host itself, and not
from another box on the same private network — both answer a question you did not ask. In this project's field
run the check was made from a second host in another country: bind a listener on the new
node one port at a time, probe it from that other machine, remove the listener.

**And distrust the probe before you distrust the firewall.** In that same run one
privileged port appeared shut and was not: the probing process was running as an
unprivileged account and could not bind that port at all. A privileged port needs a
privileged probe on both ends. That is what a false negative looks like here, and it is
exactly the trap that ends with someone filing a support ticket about a firewall that was
open the whole time.

### What it deliberately does not do

- **It does not register the node.** When it finishes the host is drivable and the fleet
  still does not know it exists. The node record is created by you, in the panel.
- **It does not harden the host.** Password authentication, unattended upgrades, a ban
  daemon, the clock and the kernel are all still yours. "Ready" here means ready to be
  driven by the control plane, and nothing wider.
- **It proves nothing about reachability.** Its checks ask *this host* questions and never
  send a packet anywhere. Whether a user inside Russia can reach this node is a field
  observation on a real network, and no run of this script is evidence for it.
- **Its ufw log sweep is not a cleanup.** On a host that had already logged, rsyslog,
  `kern.log` and the kernel journal hold the same lines, and nothing done on the host
  reaches all four. The real protection is the ordering — logging off *before* the
  firewall comes up — which is why a host prepared by this script never writes the record
  at all, and why a host that already did needs you rather than a script.

---

## Installing hashi

One procedure for every arrangement in *Where the three roles go*. Where a step reads
differently on a box that carries more than one role, the step says so; there is no other
branch. On a one-box install, the steps that name a second box (the hop, a second box's
preparation) are the ones you skip, and the rest are typed on that one box — its own node
preparation included.

### Ship the code to the control-plane box

From your own machine, in your checkout. A `git clone` on the box fails twice over: the
repository is private and the box holds no credential for it, and `/opt` belongs to root, so
an ordinary account cannot create the directory. This ships one commit's tree over the SSH
access you already have, and needs nothing on the box but `tar`:

```bash
ssh -t ACCOUNT@THE_PANEL_HOST 'sudo install -d -o ACCOUNT -g ACCOUNT /opt/hashi-control'
git archive REF | ssh ACCOUNT@THE_PANEL_HOST 'tar -x -C /opt/hashi-control'
```

`ACCOUNT` is the ordinary account every `make` target below runs as, and it owns the
checkout; it has to be in the `docker` group (*What every box must already have*). `REF` is
the commit you ran `make verify` on — `main`, or a tag. **Upgrading is the second line
again with the new ref.** `tar` adds and overwrites and removes nothing, so a file the new
tree deleted stays on the box: `git diff --name-only --diff-filter=D OLD_REF NEW_REF` lists
them, and they are yours to delete.

The box gets the tree and no `.git`, and that is the point: nothing on the most exposed
machine in the fleet can read the repository. **If you want `git pull` on the box
instead**, give it a deploy key — a key generated on the box and added to the repository as
a read-only deploy key — and `git clone` into the directory the first line made. That box
then holds a credential that reads the code (never the secrets, which are not in it); the
choice is recorded in `docs/decisions.md`, 2026-10-03.

### Bring up the control plane

On the box you chose for **C**, in `/opt/hashi-control`. **Every `make` line runs as the
account that owns the checkout, never under `sudo`**: a target run as root writes root-owned
files into a checkout the owner then cannot update, and the management tunnel's host file
lands in root's home rather than the owner's. Every line that changes the host — the firewall, the tunnel, `sysctl` —
is `sudo`, and says so.

**This is 17 commands on 16 lines, and `panel-bootstrap.sh` is one of them.** It is the
honest one — it refuses to invent your secret key, it verifies the control plane answers
before it claims success, and a second run changes nothing — but it is a step inside this
block and not the whole of it, and the charter's *one script per host* is about nodes
before it is about this box. On a host that is genuinely bare, the prerequisites in *What
every box must already have* come first, and the code (*Ship the code*, above).

```bash
cd /opt/hashi-control                                # as ACCOUNT, the checkout's owner
cp .env.example .env && "${EDITOR:-vi}" .env         # see the table above

sudo ufw logging off                                 # FIRST, always — see below
sudo ufw allow <the port sshd listens on>/tcp        # sshd -T | awk '/^port /{print $2}'
sudo ufw allow <Caddy's plain-HTTP port>/tcp         # the ACME challenge and the redirect
sudo ufw allow <Caddy's HTTPS port>/tcp              # the DELIVERY endpoint, not the console
sudo ufw enable

HASHI_MGMT_CONFIGS_TO=~/mgmt-devices make panel-bootstrap      # as ACCOUNT

# The next six lines are the SHAPE of what the run just printed. Copy them from its output:
# it prints them with this host's real path, and that path is not one to guess.
sudo install -d -m 700 /etc/amnezia/amneziawg
sudo ln -sfn <the path the run printed>/awg-mgmt.conf /etc/amnezia/amneziawg/awg-mgmt.conf
sudo ufw allow <HASHI_MGMT_PORT>/udp
echo 'net.ipv4.ip_nonlocal_bind = 1' | sudo tee /etc/sysctl.d/60-hashi-mgmt.conf
sudo sysctl --system
sudo systemctl enable --now awg-quick@awg-mgmt

make up-panel                       # as ACCOUNT, once HASHI_PRIVATE_BIND_ADDR is the tunnel's

curl -o /dev/null -w "%{http_code}\n" https://<your panel host>/panel/    # expect 404
```

**The six tunnel lines sit between the two `make` lines because `make up-panel` needs
them.** With `HASHI_PRIVATE_BIND_ADDR` set, it publishes the console on the tunnel's
address, and docker binds that address only if the host holds it or `ip_nonlocal_bind` is
on — a block that went straight from the bootstrap to `make up-panel` failed there on a
from-scratch install. What each line is for is *Bringing it up, and keeping it up across a
reboot*; the device configs land in `~/mgmt-devices`, and moving them to your devices is
*The management tunnel*. **With no `HASHI_MGMT_*` values there is no tunnel**: the run
prints none of those lines, skip them, leave `HASHI_PRIVATE_BIND_ADDR` unset, and publish
with `make up-panel-over-ssh` instead.

**That `404` is the milestone working.** The console is not on the public hostname — it is
on the private site, reached over the management tunnel or over the SSH forward. See
*Reaching the panel* above, which is also where the console's own port is opened.

Ship to `/opt/hashi-control`, **not** `/opt/hashi` — that path is the node stack's own
root, and on a box that is also a node both live on the same disk.

**`ufw logging off` comes first and is not optional.** `ufw enable` turns connection
logging on by default and starts writing source addresses to `/var/log/ufw.log` from the
moment the firewall comes up. That is a connection log — the one record the charter
forbids at any level and the one that can hurt a real person (`docs/decisions.md`,
decision 5). On this project's own leaf host it had collected 5840 bytes. Doing it after
`enable` is too late, and deleting the file afterwards is not a repair: rsyslog,
`kern.log` and the journal hold the same lines, and nothing on the host reaches all four.
Off before up is the only version of this that works.

**None of those ports is a number to copy from here.** They are the ports your own
configuration uses: read them from `sshd -T`, from your Caddyfile's site addresses, and
from the transport in the node record. A port written into a runbook becomes a port the
fleet cannot move away from — the same rule that keeps one out of the code. **No
transport port is in this block**, on a box that is also a node either: that box gets a
run of `scripts/node-bootstrap.sh` like any other node (*Prepare every node*, below), and
that run opens each transport's port from its `--port` arguments, in the right order.

### Prepare every node

Each box that carries **E** or **L** gets one run of *Preparing a node* above — the
control plane's own box too, when it carries one of them (*The control plane's own box, when
it is also a node*, there). The script is the same whichever end a node turns out to be.

**Choose the hop's UDP port before you run the script on the leaf**, and pass it as a
`--port` there: the leaf is the end that listens, `node-bootstrap.sh` is what opens the
port in its firewall, and *Build the hop* is where the form asks you for that number. An
acceptance walk did it in the other order, reached the hop form with a port nothing had
opened, and had to run the script on the leaf a second time — safe, purely additive, and
one more command than the procedure needs. Nothing in the product warns you, because the
script is not told which role the host will be registered in.

### What each role lets in

Per role, so a box carrying two roles opens both rows. Every port is your own
configuration's — read it off `sshd -T`, the Caddyfile and the node record.

| Role | Inbound | Outbound |
|---|---|---|
| **C** control plane | its SSH port; Caddy's HTTP and HTTPS ports (the delivery endpoint) | SSH to every node's SSH port |
| **E** entry | its SSH port, from the control plane; each user-facing transport's port; TCP 443 once it is a delivery host | the hop's UDP port, to the leaf |
| **L** leaf | its SSH port, from the control plane; the hop's UDP port, from the entry | — |

The control plane reaches its **own** box over SSH too, out through the public address and
back in, so on a box that carries C and a node role that box's firewall must let SSH in
from its own address — which the control-plane block's `ufw allow` for sshd's port, or the
node script's run, already arranges.

### Register each box as a node

In the panel — reached over the management tunnel or the SSH forward, never over the public
hostname (*Reaching the panel*) — **Add node** once per box that carries E or L. The values
are the arrangement; the form is the same for all of them.

- **`ssh_host`** — the address the control container reaches that box at over SSH. For the
  control plane's own box that is **its own public address**, the same one users are given:
  the control plane runs in a container, from inside it `localhost` is the container itself,
  so it reaches its own host the way it reaches any other — out through that address and
  back in over SSH (the 2026-10-02 field walk measured exactly this). `172.17.0.1` is the
  fallback if the public address is awkward. For any other box, its real remote address;
  the control container needs outbound SSH to each.
- **`ssh_user`, `ssh_port`** — from the `register it in the panel` line of that box's
  script run, the control plane's own box included. The private key is the contents of
  `~/.ssh/hashi-node`.
- **`address`** — what a user's device dials. **A name or an IP, and on the entry the
  choice is not cosmetic:** a node registered under a name is one that can answer its own
  users' refreshes (*Which host answers a refresh*, below), and one registered by IP never
  is. On the control plane's own box it makes no difference to delivery — that box answers
  refreshes as the control plane already.
- **`resolver`** on the entry, whenever it dials a hop: such a node does not render without
  one (*A node that dials a hop needs a resolver*, below).

### Enable a user-facing transport on the entry

On a node that dials **no** hop — a one-box install, or a leaf whose own users exit there —
**`amneziawg`** is the right choice. Its plain cousin is not offered — see *What to give an
entry node's users instead* for what was measured. The form asks one more thing for this
family — **how many users this row may hand an address to**, counted up from
`peer_tunnel_address`. Size it for the fleet you expect rather than for today's: the number
is a ceiling, raising it later is a resize, and the box says how many people it is being
measured against.

On a node that **dials a hop** — the entry, in every arrangement with a separate leaf — enable
a **user-facing** transport the table in *The one combination that will not render* (below)
marks yes for a node with a hop: `vless-reality` unless you have a reason for the other one,
with a `decoy_host` of your own choosing and never a shared one. The panel refuses a kernel
tunnel there, in whichever order you build the two.

Read *The one combination that will not render* before you make a one-box install's node the
entry end of a hop: once a node dials a hop, the `amneziawg` row its users hold is what the
hop form refuses. *Growing out of one box*, below, is the way round it.

**And TCP 443 is not this transport's on every box.** On the control plane's own box Caddy
holds it for the delivery endpoint; on a delivery host the delivery listener holds it, and
the panel refuses the port (*Rules that are not optional*). Reality's whole camouflage is
*being* on 443. Its declared range is `(443, 65535)`, so 8443 validates — but a TLS
"website" answering on an odd port is a signal in itself, and that cost is the one the
arrangement table names. Only an entry that is neither — no control plane on it and no
delivery served from it — has 443 to give Reality.

### Build the hop

Skip this on a one-box install. Otherwise, from the panel's hop form: entry = E, leaf = L,
transport = `amneziawg`. The entry dials the leaf, always — an entry sits behind a Russian
carrier NAT and cannot be dialled — so L listens and E reaches out, on the port you opened
when you prepared L.

Users only ever hold the entry's address. A blocked leaf is replaced by preparing a new one
and re-pointing this one hop at it, with nobody touching their device.

A hop is never granted to a user and never appears in a subscription: a user holding the
entry↔leaf tunnel would route straight past the entry the topology exists to hide behind.

### Apply, then add users — adding and revoking apply themselves

1. **Apply every node.** Until you do, the hop exists only in the database. Each node is
   serving at this point and nobody is on it yet.
2. **Add a user**, and read the dialog that opens. **The add applies by itself** (M32): the
   dialog lists one row per serving node the user was given access on, and applies each in
   turn — `✓` when that node is running the new configuration, `✗` with the reason and,
   where pressing again can change the outcome, a **retry**. Every apply restarts what
   changed on that node, so whoever is connected there drops for a second or two; adding
   several people at once (one nickname per line) costs that once per node, not once per
   person. A user holding a link-shaped protocol (the VLESS pair) is handed one link. The
   WireGuard family is a config *file* rather than a URI, so a user holding `amneziawg` is
   shown **two links**: the *subscription link*, and beneath it the *config-file link* —
   the same token asking `?format=client-config-file`. The config-file link downloads an
   archive; unzip it and import the `.conf` into the AmneziaWG app. The subscription link
   is empty for a user whose nodes offer only `amneziawg` — the dialog says so under it —
   and empty is not an error. Hand the user both: a link-shaped protocol offered later
   arrives in the first on its own. **"show link"** on the Users screen opens the same
   dialog again.
3. **Revoking applies by itself too**, on every node the user held access on.

**A manual Apply is for every other change** — a transport's parameters, a decoy, a
resolver, a pool resized, a hop built or re-pointed. Each of those changes what the panel
*would* push and touches no host until that node is applied — by you, or, on an entry with
direct sites switched on, by the nightly run (*What happens at night*, below). The panel says which nodes are behind in
one block, labelled **not applied**, on the Overview, the Users screen, the Nodes screen and
the link dialog, with an **Apply** button per node; a `✗` row in the add dialog, or a dialog
closed before every row answered, leaves its node in that block too. Until that node is
applied, a user added since has a link that names it and nothing of theirs on it.

**Bringing someone back after a revoke is a new user under a new name.** The panel refuses
an add whose nickname is already taken — `a user called '<name>' already exists` — and a
revoked user keeps theirs, so add them as, say, `<name>2` and hand over the new link; the
old one stays dead.

### Verify on the box

```bash
cd /opt/hashi && docker compose ps      # the node stack, project: hashi-node
```

On the control plane's own box, when it is also a node, two data-plane containers in two
compose projects (`hashi` and `hashi-node`) is the expected picture. On a delivery host the
node stack carries one more service, the listener that answers refreshes.

### Which host answers a refresh

**Every user's link is the control plane's, on every arrangement:**
`https://<HASHI_PUBLIC_HOST>/sub/<token>`, answered by the box you ran the control-plane
block on. That is the whole of delivery on C+E+L and C+E | L — the control plane's box is
the entry's box, so a user's refresh already comes from the entry's side of the border —
and nothing below needs doing there: no second name, no second certificate, nothing in
`.env`.

**On C+L | E and C | E | L, an entry can also answer its own users' refreshes**, so a
refresh survives the control plane being behind a closed border. Nothing turns it on and
nothing names it; an apply makes a node a **delivery host** when, at that apply, all four of
these hold:

1. the node carries an enabled **user-facing** transport — a leaf that holds only the far
   end of a hop has nobody to answer;
2. its `address` is a **name** (with a dot in it) and not an IP — a public certificate
   authority does not issue for an address;
3. this control plane holds a **usable, unexpired delivery certificate** (below);
4. the box does **not** hold this control plane's own compose project (`hashi`) — read off
   the host over the apply's own connection, which is why a co-located box never becomes
   one whatever its record says.

The Nodes screen says, per node, whether it answers refreshes, under which name, and how long
the certificate it is holding has left. A delivery link is a second link and never the
first one moved — *Moving the delivery endpoint, and what users have to be told* is what
an operator owes users about it, and the panel composes no delivery link for a particular
person today.

**The name has to resolve to that host, and the product does nothing about DNS**: it
creates no record, moves none and checks none.

### The delivery certificate

Needed only on C+L | E and C | E | L, and only if you want the entry to answer refreshes.
**Both blank — the default — is a supported mode**: no node serves refreshes of its own and
every user fetches from the control plane, exactly as on the other arrangements.

**One wildcard for the fleet, issued by you, today.** The control plane does not issue it
(that is M30, not built); you obtain a certificate for `*.<a zone you own>` and put the pair
on the control plane's box:

- **The files go in `deploy/delivery/`**, which compose mounts read-only inside the
  control container at `/etc/hashi/delivery`; `HASHI_DELIVERY_CERTIFICATE_PATH` and
  `HASHI_DELIVERY_KEY_PATH` name them **by their path inside the container**, and
  `.env.example` gives the two values that work. A path on the host is a path the control
  plane cannot open.
- **Readable by uid 999**, the account the control plane runs as — `chown 999:999` both
  files, or `chgrp 999` and `chmod 0640`. At the 0600 a private key normally carries the
  control plane refuses the pair, and the Nodes screen says so and names the path.
- **Issue it for a zone that carries nothing else, and never the one `HASHI_PUBLIC_HOST`
  is in.** The private key is pushed to every delivery host — the machines most likely to
  be seized — and whoever holds it can answer for any name the certificate covers, until it
  expires. One wildcard rather than one per host because every issued certificate is
  published in a Certificate Transparency log within minutes, and one per host would
  publish every entry's name as it was created.
- **Renewal is replacing the two files, then an apply on every delivery host.** The pair is
  read on every apply and never cached, and a host is handed the current one only by an
  apply that reaches it. Check the mode again each time: `cp -p` preserves the issuer's
  0600, and a certbot deploy hook writes its own.

**What a delivery host can do under a shutdown is bounded by the certificate it already
holds.** Nothing renews it across a closed border, because renewal is an apply and an apply
is the control plane reaching the node. An apply made while the control plane's pair is
expired or unreadable stands that host's listener down and takes the key off it; a host no
apply reaches goes on serving what it was last given, under a certificate that expires on
its own date. The Nodes screen shows that date per host — read it before the border shuts,
not after.

**What a delivery host holds** is under `/opt/hashi` like everything else the control
plane pushes: the site its listener serves, the certificate and its key, and the rendered
subscription of each user it serves, in both shapes — that host's own entries and nothing
from any other node, under a name derived from the token rather than the token itself. A WireGuard-family user's
archive carries their client `PrivateKey`, which the node's own server config never holds.
When the material goes, and the states in which it does not, is *When a delivery host
stops being one*, below.

---

## Growing out of one box — the box you have becomes the leaf

**This is the move most operators actually make.** You ran a one-box install because this
page calls it the right first run: one box abroad, carrying the control plane and a node,
with `amneziawg` for your users. Months later you rent a Russian box, and the charter's
topology becomes buildable for the first time. The arrangement goes from C+E+L to C+L | E,
and the procedure above still describes every step of it — what is written here is which
box takes which role, because the obvious reading of that is expensive.

**Do not make the box you already have the entry.** Giving a hop to a node that already
offers its users a kernel tunnel is refused at the hop form — *no hop was established —
`E` already offers `amneziawg` to its users …* — and correctly, because that node could
never render again (*The one combination that will not render*, below). The refusal names
two ways out, and **the one you will reach for is the one that costs you every user on
that box.** Removal is what destroys material, and the panel says so before you confirm:

> `amneziawg` removed from `E` — *out of every user's link at their next refresh, and the
> material minted for it is gone with it.*

Every user on that box then loses the credential their device is connecting on, and the
repair is to reach all of them with a new configuration — over whatever channel you have,
on the day you have just taken their working one away.

**So point the move the other way.** The box you already have becomes the **leaf**. The
box you just rented becomes the **entry**. The tunnel your users are connecting on is on
the box that does not move, so nothing they hold has to change and nobody is cut off at
any point of this.

| | before | after |
|---|---|---|
| the box you have, abroad | control plane, and `amneziawg` for your users | both of those, unchanged, **plus the leaf end of the hop** |
| the box you rent, in Russia | — | the entry: a user-facing VLESS transport, and it dials the hop |

**A leaf carrying both is supported, not a workaround.** A leaf's users exit by the
leaf's own route — that is route B, and a hop landing on the same box does not touch it —
so one node holds `amneziawg` for its users and `amneziawg` for the leaf end of the hop,
both enabled, and every user on the first row goes on connecting. Two rows on one node
need two ports and two ranges of their own (*Rules that are not optional*, below); nothing
else about them collides, and neither has to be taken away for the other to exist.

1. **Prepare the new box** with *Preparing a node* above — the script is the same
   whichever end a node turns out to be — and register it. Give it a `resolver` as you
   register it: it is about to dial a hop, and such a node does not render without one
   (*A node that dials a hop needs a resolver*, below). Register it under a **name** if you
   want it to answer its own users' refreshes (*Which host answers a refresh*, above).
2. **Enable a user-facing transport on it** — `vless-reality` unless you have a reason
   for the other one, with a `decoy_host` of your own choosing and never a shared one.
   This box dials a hop, so it is the one node in your fleet whose users may not be on
   a kernel tunnel. The panel is not on this machine, so 443 is Reality's here — unless
   this box becomes a delivery host, whose listener holds it (*Enable a user-facing
   transport on the entry*, above).
3. **Build the hop** from the panel's hop form: entry = the box you rented, leaf = the
   box you already have, transport = `amneziawg`. The entry dials and the leaf listens,
   so the hop's UDP port is opened on the firewall of the box you have been running for
   months, not on the new one.
4. **Apply both nodes.** Until you do, the hop exists only in the database.
5. **Nothing your users already hold stops working.** Enabling that transport granted
   every active user material on it, so the new entry is in every subscription at the
   next refresh — on the *subscription* link, since the VLESS pair is a URI list while the
   `amneziawg` they are connecting on is a config file (*The one combination that will
   not render*, below). The tunnel on their device is untouched. Taking the new way up
   is them loading that link into a client that speaks VLESS, once, at their own pace.

**When you want everybody behind the entry, withdraw the leaf's user-facing row —
do not remove it.** Withdrawing takes it out of every user's link at their next refresh,
leaves every credential minted, and is one press to undo if the new path disappoints you;
apply the leaf afterwards, or the host goes on serving what it was last given. Two things
to have done first: watched a user's traffic actually come out of the entry, and given
everyone still on the old tunnel time to load the new link, because this is the press that
takes their working route away. Removal is the irreversible one and there is no reason at
all to reach for it on this path.

**What this costs** is the C+L | E row of *Where the three roles go*: `HASHI_SECRET_KEY`
never travels to Russia, and the control plane's own refresh URL is now outside it. The
entry answers its own users' refreshes from inside only once it is a delivery host, which
needs it registered under a name and the delivery certificate above; without those, a user
inside Russia may be unable to refresh at exactly the moment a whitelist shutdown makes
them need to.

---

## The one combination that will not render

**On a node that dials a hop, users may not be on a kernel tunnel.** Following this
runbook used to produce exactly that: `amneziawg` for the entry's users, because the
one-box install names it, and `amneziawg` for the hop the entry dials, because the hop
requires it.

**The panel refuses it at both doors, before anything is written.** Enable such a
transport for the users of a node that already dials a hop and the dialog answers *nothing
was enabled — this node's traffic leaves through a hop, and `amneziawg` cannot carry a
user's out through one …*; build a hop from a node that already offers one to its users and
the hop form answers *no hop was established — `<node>` already offers `amneziawg` to its
users …*. Both name the two ways out: give that node's users a transport that terminates
their connection and re-originates it, or take the other row away. Nothing is enabled,
nobody is granted anything, and no user is handed a file.

That refusal is M25's, and it is worth knowing what it replaced. Until then the panel took
both rows without a word, granted every user a credential on the new one, and handed one of
them a complete, importable configuration file over their own subscription link — for a
node whose apply then refused to render it. Three yeses and a no, in that order, with the
no arriving last.

Two instances of one transport on one node are otherwise ordinary — they collide on a
**listening port**, on a **config name** and, for the WireGuard family, on their **tunnel
ranges**, which may not overlap (*Rules that are not optional*, below). On a **leaf** they
are exactly right: give the hop a range of its own and two `amneziawg` rows on two ports
share none of the three. It is the node that DIALS the hop that may not also hand one to
its users.

**If a node is already in that state, the apply is still what refuses it** — a fleet built
before this refusal existed, or a database edited by hand. It arrives as a banner on the
Nodes screen:

> `amneziawg could not be rendered for this node — EgressNotRenderable:` … *A tunnel whose
> packets this node's kernel routes cannot send them out through a different interface, so
> they would leave by the node's own route instead — which is the silent failure the hop
> exists to prevent. Give this node's users a transport that terminates their connection
> and re-originates it, or take the hop away.*

**That banner is the only signal you get, and the node does not go `degraded`.** The
refusal happens while the configuration is being rendered, before anything is written to
the host, so there is no half-configured node to mark and the node's state is left exactly
as it was. An entry that was already `active` therefore **stays active and stays in every
user's link**, serving whatever its last successful apply left on the host — an operator
scanning the Nodes screen for something red finds nothing. Read the banner, and treat a
node whose apply you cannot complete as one that is serving a configuration you did not
choose. The way out is the one the doors name: take one of the two rows away.

**That is a refusal, not a defect.** A wg-quick-family tunnel hands a user's decrypted
packets to the entry's own routing table, and the only route this project renders for a
hop is source-based, from the hop interface's own address. A user's packets never match
it, so they would leave by the entry's own route — an exit in the country the hop exists
to leave, with every screen green. Refusing beats that (`docs/decisions.md`, decision 3).
The **leaf** end of the same hop renders fine; it is the user-facing side on the entry
that cannot.

**What to give an entry node's users instead.** A transport whose data plane
*terminates* the connection and originates a new one, which is what the refusal asks for.
In this image that is the VLESS pair, `vless-reality` and `vless-ws-tls`. Both are Xray,
which forwards no packet in the kernel: it accepts the user's connection and opens its
own, and on a node with a hop that new connection is bound to the hop's near address. So
it can only reach the internet through the hop, and while the hop is down it cannot be
opened at all — fail closed, as a property of the rendered file rather than a rule someone
has to remember.

Between the two, `vless-reality` needs nothing placed on the host: it borrows a decoy's
handshake, so give it a `decoy_host` of your own choosing and never a shared one.
`vless-ws-tls` needs a real certificate and key **already on the node**, named by path —
nothing in this project puts them there — so it is the right answer only on a host where
you already terminate TLS for a name you own.

`amneziawg` stays exactly right for users on a node with **no** hop: a one-box
install, and a leaf. There the same row renders a local exit, which is the shape a real client
was measured carrying traffic on.

**Its plain cousin does not, and is retired: the panel no longer offers it.** `wireguard`
is still in the image and a node already running it still serves it — but the pinned data
plane writes its forwarding rules on one netfilter backend while the firewall this runbook
has you enable writes its default-deny policy on the other. Both are traversed, so the
accept never front-runs the drop: a user's handshake completes, nothing is carried, and
neither end says anything. Measured twice on a live node. The Transports screen states it
on the row, with the reason; the enable dialog simply does not list it.

Every transport this image ships, and what each one may be asked to do:

| transport | users on a node with a hop | users on a node with no hop | the entry→leaf hop |
|---|---|---|---|
| `vless-reality` | yes — Xray terminates the connection and originates its own | yes | no — a hop is two ends of one tunnel network that each need an address of their own, and this transport hands its consumers none: it identifies them by their material |
| `vless-ws-tls` | yes, once a certificate and key are on the node | yes, on the same condition | no, for the same reason |
| `amneziawg` | no — the panel refuses it at both doors, and an apply refuses a node already in that state | yes | yes, and today it is the only one |
| `wireguard` | no — the same refusal, for the same reason | no — retired: the panel does not offer it, and a row enabled before that carries no traffic on a host this runbook prepared | no — it is protocol-blocked where this matters, and the form will not offer it |

Every cell in it is checked against the code by `tests/infra/test_deploy_runbook.py` —
against the renderers for the first column, the panel's own enable dialog for the second,
and its hop form for the third. A fifth transport, a retirement, or a change to what one
of these can do turns that suite red rather than leaving this table quietly wrong.

**A wg-quick-family config needs a resolver tool on a plain Linux client, and what it does
without one looks like the node's fault.** The file this project generates carries a
`DNS =` line, and `awg-quick`/`wg-quick` implement that line by shelling out to
`resolvconf`. On a Linux box without it the run **brings the interface up and then deletes
it again**, which is `awg-quick`'s own error path and not a failure on the node:

```
[#] ip link add awg0 type amneziawg
[#] ...
[#] resolvconf -a awg0 -m 0 -x
/usr/bin/awg-quick: line NNN: resolvconf: command not found
[#] ip link del awg0
```

The last line an operator reads is about a program they have never heard of, after a
tunnel that appeared to work for a second. **Install `resolvconf` or `openresolv` on that
machine and run it again** — on Debian and Ubuntu that is `apt install openresolv`. Two
things it is not: nothing on the node changes and nothing on the node is wrong, and the
node's own `resolver` field is a different thing entirely — that one is for a node that
dials a hop, below. Stock GUI clients on phones and desktops resolve names themselves and
never touch `resolvconf`; it is the operator testing from a shell who meets this, which is
exactly who this page tells to *"load it into a stock client"*.

**Do not answer it by deleting the `DNS =` line.** That line is what sends a user's
lookups through the tunnel; without it their device keeps asking a resolver it can no
longer reach, and the tunnel that looked fixed resolves no names at all.

**The two families are delivered differently, and the link dialog says which is which.**
A VLESS transport rides the *subscription link*. The WireGuard family is a config file:
the same token, `?format=client-config-file`, an archive — shown in the user's link dialog
as a second, *config-file link* whenever they hold a credential on a config-file transport
that is offered, and not shown otherwise. Each link is labelled with the app that takes it
and what it carries for that person. A user whose node offers only AmneziaWG and whose
client opens the subscription link gets an empty document rather than an error — so hand
them the config-file link too, and expect the subscription link to carry entries once a
VLESS transport is offered to them. **A file does not refresh itself:** after a node of
theirs changes (a key rotated, a node replaced), they download the config-file link again
and re-import. **Offering a config-file transport to a fleet whose users already hold only
the subscription link** means each of them now has a second link to be handed — the
enable dialog says so before the press, and the toast of offering it again does after.

### If you already built it the other way

The way out is in the panel, and it is **removal** rather than withdrawal. Withdrawing the
user-facing `amneziawg` does stop the apply failing — a withdrawn row is not rendered at
all — but it leaves the row on the node still holding its listening port, its config name
and its tunnel range, its users' material still minted for a transport that node can no
longer render, and a trap for whoever offers it again: the same apply fails the same way.
Removing it takes the row, the material, the port, the name and the range.

1. **Nodes → transports** on the entry box. Both `amneziawg` rows are listed, and the
   second one created carries a config name of its own — it reads `amneziawg
   (amneziawg-2)` — so the two cannot be confused. The hop end is the row whose standing
   begins *one end of a hop*, and it is drawn with no buttons at all.
2. **remove** the user-facing one, and read the dialog before you confirm: removal
   destroys the material every user holds on that row and frees its port, its config name
   and its tunnel range, and it is the only action that does any of the three. `withdraw`
   beside it is the reversible one, and it is not what gets you out of this.
3. **Enable a VLESS transport** for users on that node, on a port nothing else there
   listens on.
4. **Apply the node.** Removal does not push: until you apply, the host is still running
   the container the panel has stopped showing.

Two things removal deliberately does not do. It does not revoke anybody — those users lose
that one entry at their next refresh and keep everything else. And it does not unlink the
config the last apply wrote under `/opt/hashi/conf/`: that file still holds the node's
private key and every credential that transport carried, and nothing in this project ever
unlinks a rendered config — the same is true after a withdrawal and after a dissolved hop.
Once you have applied, nothing on the node serves that file and no copy of what is in it
remains in this panel; what is left is key material at rest on a host that can be seized.

**So delete it, and it is the one exception to *never edit anything under `/opt/hashi`*.**
After the apply that removed the service:

```bash
ls /opt/hashi/conf/                              # every rendered config on this node
rm /opt/hashi/conf/THE_CONFIG_NAME.THE_EXTENSION # the name the panel showed on that row
```

**The extension is the transport's, not a fixed one** — the WireGuard family is written
`.conf`, because wg-quick takes the interface name from the file name and loads nothing
else; the VLESS pair is written `.json`, because Xray reads JSON. So the file this
section's own advice leaves behind — the `amneziawg` you removed — is a `.conf`, and the
next one you orphan, once that node's users are on a VLESS transport, is a `.json`
holding that transport's node key, its secret path and every user's id. Both are the same
kind of residue and both are covered by this exception. `ls` first, and go by the config
name the row carried.

**Only for a transport that is no longer enabled on that node.** The standing rule holds
for every other file there, and for the reason it gives — the control plane generates them
and overwrites them on every apply. An orphan is the exception precisely because nothing
regenerates it, which is what puts it outside that reason. `docs/tracker/field-checklist.md`
carries the same carve-out; if the two ever disagree, they are describing the same file and
one of them is stale.

To take the hop away instead, use the **Hops** screen. Removing or withdrawing one end of
a hop is refused wherever you ask for it, because it would leave the other end holding a
tunnel to an exit that is no longer configured.

## A node that dials a hop needs a resolver

**On a node that dials a hop, a user's destination names are looked up through the hop,
at a resolver named on the node's record — never by the host's own.** Before this, the exit
had moved abroad and the lookups had not: the proxy asked the entry host's resolver, inside
the network the hop exists to leave, one query per site a user visited
(`docs/decisions.md`, 2026-09-09). Whichever resolver you name still sees the names — from
the far end of the hop rather than from the entry's network, which is the exposure that
decision accepts knowingly.

A node that dials a hop and has no resolver is refused at **apply**, on the entry, with this
in a banner on the Nodes screen:

> `vless-reality could not be rendered for this node — ResolverMissing:` *this node's
> traffic leaves through a hop, and its record names no resolver for the destinations its
> users ask for. Without one they would be looked up by this host's own resolver — on
> the near side of the hop, inside the network the hop exists to leave — while the traffic
> itself exits at the far end. Nothing is rendered until the node has one: an IPv4 address
> the far end of the hop can reach.*

Like the refusal above, it happens while the configuration is being rendered, so the node
does not go `degraded`: an entry that was already `active` **stays active on whatever its
last successful apply left** — its users' lookups still going to the host's resolver — and
a user you revoke **keeps working there**, because a revocation's re-push is a render too.
The revocation's banner says so, naming the node.

**Do it right after the upgrade that brings this refusal — before the next apply, and before
you revoke anybody: give every node that dials a hop its resolver.** The upgrade adds the
field empty on every existing node, because any value it wrote would be a resolver this
project chose for you; from that moment each existing entry is in the state described above.

1. **Nodes → resolver** on each node that is the entry end of a hop — the Hops screen lists
   them. Give an IPv4 address the far end of the hop can reach: a public resolver of your
   choosing, or one inside the leaf's own network. A name is refused, and so is a loopback
   address — a stub resolver on the entry would answer from the entry. **An address the
   entry itself holds on one of its own interfaces is the case nothing here can catch:**
   the host answers it locally, on the near side of the hop, and neither the panel nor
   `edge` can see which addresses a host holds. Avoiding that one is yours. The same call
   without the panel is `POST /api/nodes/<id>/resolver` with `{"resolver": "<address>"}`.
2. **Apply the node.** Setting the resolver changes the record, not the host.

A new node takes its resolver in **Add a node**, in the box of the same name. A node that
never dials a hop leaves it empty: its lookups and its exit already leave from the same
place, and its configuration does not change.

---

## Sites that only open from Russia (direct sites)

Some sites refuse every visitor whose address is not Russian — state services, banks, a few
shops. A user on the VLESS path reaches the internet from the LEAF's foreign address, so
those sites refuse them. **Direct sites** (M34) lets an entry node open the sites on a list
from its OWN Russian address instead, and everything else goes through the hop as before.
It changes nothing on anyone's phone and nothing for config-file (AmneziaWG) users, whose
tunnel goes straight to the leaf.

The cost is the point and is worth saying out loud: **a listed site sees the entry's
address, not the leaf's.** While the hop is down, listed sites still open and nothing else
does — there is no fallback for unlisted sites.

### Switching it on

1. **Routing** screen → *Suggested* → **add** `itdoginfo-russia-outside`. That is the narrow
   list the owner chose: sites that do not open from abroad (about forty names). The three
   broader roscomvpn lists are offered too and are added switched off. Any https text list
   with one site per line can be added with **add source**. The suggestions come from
   `HASHI_ROUTING_SUGGESTED_SOURCES` (default in `deploy/docker-compose.yml`; `.env` may
   replace it).
2. **fetch now**. Adding fetches nothing. The control plane fetches — never a node — and the
   screen updates when it is done. A source that cannot be fetched keeps whatever version was
   in force, and its row says how old that is.
3. **Nodes** screen → the entry → **direct sites**. Give the **resolver for listed sites**:
   an IPv4 resolver on the entry's own side of the border, so a listed site answers as it
   would a Russian visitor. The resolver the entry's hosting provider hands the host is the
   natural choice (`resolvectl status` on the entry shows it — not `127.0.0.53`, which is the
   host's stub and is refused). It must differ from the node's other resolver (the M16 one,
   reached through the hop); the dialog refuses the same address for both. **switch on**.
4. **apply** the entry. Applying restarts its proxy: anyone connected through it is dropped
   for a second or two.

Your own lists, on the same screen (**add entry**): *always direct* adds sites; *never
direct* keeps a site on the hop even when a source lists it, and wins over everything. A
name covers every name under it. **Where would it go?** answers for one site or address
from the lists alone; nothing typed there is kept.

### What happens at night

Every night at `HASHI_BACKUP_AT` in `HASHI_BACKUP_TZ` — the backup's hour, read by the
control plane too — the sources that are on are fetched (only while some entry has direct
sites on), and every entry whose config changed is applied. A fetched list that looks wrong
is **held** instead, with its diff on the Routing screen, until you **approve** or
**reject** it: any line that is not a site or an address range (an error page in place of a
list), an empty list, more than `HASHI_ROUTING_MAX_ENTRIES` (20000) entries, or a list that
grew or shrank by more than `HASHI_ROUTING_MAX_CHANGE` (half) in one fetch. A rejected
content is not asked about again. `HASHI_ROUTING_CHECK_INTERVAL=0` turns the nightly run
off. A malformed hour or an unknown zone falls back the way the backup does (04:00, UTC) and
the Routing screen says so.

An entry that was behind for another reason when the night comes gets that change too; turn
its switch off if it must be left alone.

### Checking it on the real hosts

From a phone on the entry's VLESS link: open a site on the narrow list that shows the
visitor's address (`showip.net` is on it) — it must show the **entry's** address. Open an
address-echo site that is on no list (for example `ifconfig.me`) — it must show the
**leaf's**. Put the first site on *never direct*, apply, and it shows the leaf's. Stop the
hop — `docker ps` on the leaf lists its hop container; `docker stop` it — and the listed site
still opens while the unlisted one does not; `docker start` it again afterwards.

Nothing records who reached what: the entry's container log stays at `warning` with access
and DNS logging off, the Routing screen shows the lists and never their use, and the lookup
writes nothing. The lists themselves are in the control database and therefore in every
backup — they are public data and your own two lists, not anything about a user.

## Adding a user from Telegram (the owner's bot)

A long-polling bot that takes one command from one Telegram account — yours — and runs
the add the panel's dialog runs: create the user, push them to every serving node, hand
back the links. Nothing else, from nobody else. Since M39 it is **its own container**
beside the control plane (`telegram-bot` in `deploy/docker-compose.yml`), tied to the
panel only by the shared database — the control plane itself no longer polls. It is
**off** until the `telegram-bot` profile is switched on with the two lines below in
`.env`; an install that does neither is unchanged — the container is never started, no
task runs and no log holds a Telegram line. The bot dials Telegram outbound; nothing
listens, nothing is published, and Caddy is not touched.

### Switching it on

1. **Create the bot at BotFather.** In Telegram, open `@BotFather`, send `/newbot`, give
   it a display name and a username ending in `bot`. BotFather answers with the token —
   `<digits>:<a long string>` — which is the credential (the cautions below). Nothing
   else needs setting there: no commands menu, no privacy mode, no group.
2. **Find your own numeric id, and do it BEFORE the control plane polls.** Open the chat
   with your new bot and send it anything — `/start` will do. Then, from any machine that
   reaches Telegram:
   ```bash
   curl "https://api.telegram.org/bot<token>/getUpdates"
   ```
   The answer holds your message; read `result[0].message.from.id` — a plain number, the
   same as `chat.id` in a private chat. That number is your id; a username is not (it can
   be changed and reassigned, the number cannot). No third-party "what is my id" bot is
   needed, and none should be handed this token. If `result` is `[]`, send the bot another
   message and run the `curl` again.
   **The order matters.** Once the bot polls, it confirms every update it reads by offset,
   so your message is gone from the next `getUpdates` — and Telegram answers a second poller
   on the same token with `409 Conflict`. The `curl` runs first, and nothing else may poll
   this token while the bot does.
3. **The `.env` lines**, on the control-plane box (`.env.example` carries the same three
   under *the owner's Telegram bot*):
   ```
   HASHI_TELEGRAM_BOT_TOKEN=<the token from step 1>
   HASHI_TELEGRAM_OWNER_ID=<the number from step 2>
   ```
   Both or neither. One without the other stops the **bot container** at boot with a
   sentence that begins `HASHI_TELEGRAM_BOT_TOKEN and HASHI_TELEGRAM_OWNER_ID are set
   together or not at all` and ends `Refusing to start.` — `make logs PROFILES=telegram-bot`
   shows it under `telegram-bot`. The control plane no longer reads these two, so it boots
   either way; it is the bot that refuses half a pair. A third line, `HASHI_TELEGRAM_API_URL`,
   is where the Bot API is dialled; blank means Telegram's own, `https://api.telegram.org`,
   and it is set only to a relay you run yourself, on a box from which Telegram's address
   does not answer (*Known-unproven*, below). Building that relay is not this project's.
4. **Switch the bot on with the command this host was published with, plus
   `PROFILES=telegram-bot`** — `make up-panel PROFILES=telegram-bot` over the management
   tunnel, `make up-panel-over-ssh PROFILES=telegram-bot` without one; `make up
   PROFILES=telegram-bot` only on an install that publishes nothing, because on a published
   host plain `make up` takes the published ports away. compose starts the `telegram-bot`
   container and leaves the rest converged — the control plane is not recreated, because its
   environment has not changed (the Telegram settings reach the bot, not it). A later `up`
   without `PROFILES=telegram-bot` leaves the running bot in place; to take it down, stop the
   `telegram-bot` service by name.
5. **Watch it start**, in the bot container's log — `make logs PROFILES=telegram-bot` (plain
   `make logs` does not follow a profiled service):
   ```
   INFO control.app.services.telegram_poller: telegram: polling as @<your bot's username>
   ```
   That line is the bot: it has reached Telegram, learned its own name and is polling. It
   is written once per start of the bot container. If Telegram does not answer from this
   box, the log holds one WARNING instead — `telegram: polling is failing: Telegram could
   not be reached for getMe (ConnectError). Retrying, up to a minute apart, until Telegram
   answers; this is said once, not per retry.` (the sentence after the colon names the
   call and the reason; it never names the address or the token) — and the panel and
   `/sub/` are unaffected: the bot is a separate container, and nothing waits for it. The
   bot resumes by itself when Telegram answers again, without a restart: while it was still
   starting, the signal is the `polling as` line itself; once it had been polling, it is
   `INFO … telegram: Telegram answers again; polling resumed`.

   **On a Russian entry box, expect the WARNING, not the `polling as` line — for now.**
   Reaching `api.telegram.org` from that box is the border this whole fleet exists to cross,
   and the route the bot is meant to take — out through a leaf — is the leaf egress of M40,
   which has not landed. So until M40 the bot on the real host sits in `polling is failing`
   and answers no command, while the panel and `/sub/` serve normally. On the e2e stand the
   bot polls a fake Bot API on the compose network, so there the `polling as` line appears at
   once — the stand proves the bot composes, never that Telegram answers from Russia.

### What the bot answers

Every reply below is to a message from your id, in your private chat with the bot.

- **`/adduser <nickname>`** — several people at once is one nickname per line in the same
  message, exactly what the panel's add dialog accepts. The first reply is
  `adding, about a minute per node`; the add runs with the same validation, the same push
  to every serving node and the same trail entry as the panel's dialog (**Audit** shows
  `user <name> added`, and nothing says through which door — *Apply, then add users*,
  above). The second reply holds the links the panel hands over after an add — per
  person, the nickname, then `subscription link: <url>` and, where the person holds
  `amneziawg`, `config-file link: <url>` beneath it — and, when no node is serving, the
  dialog's own outcome sentence as the last block. When a node could not be updated, the
  links are followed by the dialog's opening — `<n> user(s) added and pushed to <k>
  node(s), but <m> node(s) could NOT be updated and do not know them yet:` — and then one
  block per such node: the reason the dialog's `✗` row shows, with the node's name in
  front (`'<name>' was not updated — it could not be reached, or the push did not finish
  — so it does not know them yet; retry, and if it fails again apply it from the Nodes
  screen to read why`, or the sentence for whatever else went wrong), and beneath it
  `apply it: /apply <name>` — the command to send as it stands (`/apply <name>`, below).
  A node the add did reach gets no such block. A reply longer than Telegram's
  4096-character limit arrives as several messages, never splitting one person's links
  across two. The links show no preview: the bot asks Telegram not to fetch them.
- **A nickname that is taken** gets, after the `adding` line, the sentence the panel
  shows — `a user called '<name>' already exists` — followed by `Nothing was added. The
  panel shows every user and their links; the bot never re-sends a link.` A revoked
  user's name is taken too; bring them back under a new name, as the panel section says.
- **`/nodes`** — which serving nodes are behind what the panel would push: the nodes the
  panel's **not applied** block names at that moment, read from the record with nothing
  dialled, so the answer is immediate. One block per node that is behind — the block's
  own sentence said of that one node, `<name> is still on the old configuration: your
  changes have not reached it.`, and beneath it `apply it: /apply <name>`, the command to
  send as it stands. When no serving node is behind, the one sentence
  `Every serving node holds the configuration it would be given.` — *serving* is the
  state it is about: a draft or degraded node is not in this answer, and the Nodes
  screen is where those are read. Anything typed after `/nodes` is ignored.
- **`/apply <name>`** — **the Nodes screen's Apply, for that one node — not the add's
  push. It can take a draft or degraded node into service, and a failure after the first
  byte is written leaves the node `degraded`; so read `/nodes` first and apply a node it
  names.** The name is everything after `/apply`, exactly as the Nodes screen spells it
  (a name may hold spaces); nothing is matched loosely, and a name no node has gets
  `no node named '<name>'` as the only reply, with nothing dialled. Otherwise the first
  reply is `applying <name> — about a minute`, and the second is what the button's toast
  says: `config applied to <name> — <the configs applied>`, with a clause naming what
  was restarted when something was; or, when the host would not answer the serving
  check, the button's unmeasured sentence (`config applied to <name> — <configs>. Not
  measured serving: <configs>. …`), which names configs and never their contents. A
  refusal or a failure is the sentence the panel's banner shows for the same press —
  nothing to apply (`… so there is nothing to apply — nothing was pushed and nothing on
  the node was changed. …`), a retired node (`this node is retired, and applying a node
  is what puts it into service — which is the one move a retired node is refused. …`), a
  host not reached (`the node could not be reached, so nothing was pushed and nothing on
  it changed: <reason>. …`) — and the node's row on the Nodes screen records what the
  apply did to its state. The one sentence that is not the banner's: a configuration
  refused by its checker before anything was pushed gets
  `'<name>' could not be given a configuration: it was refused before anything was
  pushed, and retrying will not change that — apply it from the Nodes screen to read
  why`, because the banner's sentence can quote the checker's output and a checker is
  known to quote a private key — the Nodes screen shows it, the chat never does. A
  failure that is no sentence of its own gets
  `applying <name> did not complete — the Nodes screen shows the state it was left in;
  what failed is in the control plane's log.` One node per command; there is no
  apply-everything.
- **`/start`, `/help`, a bare `/adduser` or `/apply`, and anything else** get the usage
  line: `/adduser <nickname> — one nickname per line — adds them, pushes them to every
  serving node and replies with their links. /nodes — which serving nodes are behind what
  would be pushed, with the /apply for each. /apply <name> — the Nodes screen's Apply,
  for that one node. Everything else is on the panel.`
- **Anyone else** — any other id, a group, a channel, a forwarded message — gets
  **silence, by design**: no reply, nothing created, and no log line naming who tried.
  Anybody can find a bot by its username and write to it; a refusal would confirm the bot
  acts for someone, and a log line would be a record about a person.

What it does not do, on purpose: revoke, list, re-send a link, serve a second account.
Those are the panel's — **show link** on the Users screen is where a link is read again.
And it applies one named node per command: there is no apply-everything, and the Nodes
screen has no such press either.

Commands are handled one at a time, in the order Telegram delivers them, and each is
attempted once. A command that fails inside the control plane is answered with nothing —
`/apply` with its did-not-complete sentence, above — and logged as `ERROR … telegram: an
update was not handled (<reason>). It is acknowledged and not retried; a command the
owner sent is theirs to send again.` — send it again if you want it. A command sent while
the control plane was down is held by Telegram (for up to a day) and delivered when
polling resumes; the one case that delivers a command twice — a process death between
the attempt and the next poll — turns an `/adduser` into an `already exists` reply rather
than a second user, and an `/apply` into the same node applied once more.

### Two things to know before the first `/adduser`

- **The links the bot sends you transit Telegram's servers**, exactly as they do when you
  paste them into a chat with a friend today — the bot adds no new path for a link — but
  **the chat with the bot now holds every friend's link in your account**, in one place,
  for as long as you keep the messages. Whoever reads that chat (a lost phone, a session
  left open on a machine that is not yours) reads every link in it. Delete the messages
  once a link is handed over if you want the chat to hold nothing; the panel keeps the
  links.
- **The bot token is a credential.** Whoever holds it reads your commands and writes to
  you as the bot; it belongs in `.env` and nowhere else — not in a chat, a screenshot or a
  ticket. If it leaks, revoke it at BotFather (`/mybots` → the bot → *API Token* →
  *Revoke current token*), put the new one in `.env` and bring the panel up again; the old
  token is dead the moment BotFather revokes it. The token travels in every call's URL
  path — the same shape as a subscription token — so no line the control plane writes
  names the address it dialled or the token, the failure lines above included; a token in
  a log would be a finding. Your numeric id is not a secret: it is what the bot checks,
  not what it trusts you by.

## Upgrading an install that predates the rename

**The person who uses hashi is a `user`. They used to be a `friend`** — in the API, in
the panel's routes and in the database — **and this release moves all three at once.**
**Nobody has to be sent a new link and nobody has to touch their device.** A
subscription URL issued before this is byte-identical after it, so is the token inside
it, `/sub/{token}` is untouched, no token is reissued, and a VLESS document comes back
byte for byte as it went out. A WireGuard-family config comes back with **every
functional line identical** — private key, address, MTU, the AmneziaWG obfuscation
values (`Jc`, `Jmin`, `Jmax`, `H1`–`H4`), peer key, preshared key, `AllowedIPs`,
endpoint, keepalive — and one `#` comment reworded, which `wg-quick` and `awg-quick`
ignore. The device connects on that file exactly as it did. It is not the same file,
though, and the panel counts the difference: read *Every WireGuard-family node reads as
drifted*, below, before you read the Overview.

What does change is what you can call from a script. **Anything scripted against the old
paths stops working** the day this lands. There is no alias, no redirect and no
deprecation window — the old paths answer `404`.

| was | is |
|---|---|
| `GET` / `POST /api/friends` | `GET` / `POST /api/users` |
| `GET /api/friends/{friend_id}/subscription` | `GET /api/users/{user_id}/subscription` |
| `POST /api/friends/{friend_id}/revoke` | `POST /api/users/{user_id}/revoke` |
| `/panel/friends`, `/panel/friends/table`, `/panel/friends/new` | `/panel/users`, `/panel/users/table`, `/panel/users/new` |
| `/panel/friends/{friend_id}/subscription` | `/panel/users/{user_id}/subscription` |
| `/panel/friends/{friend_id}/revoke` | `/panel/users/{user_id}/revoke` |

**And one field moved inside a body that still parses.** A revocation now answers
`user_id` where it answered `friend_id`. A consumer reading the old key gets `None`
rather than an error — nothing raises, nothing is logged, and whatever it was going to do
with that id it now does to nobody. That is worse than a `404`, because a `404` is
visible. Grep your own tooling for `friend_id` before you deploy rather than after.

### Every WireGuard-family node reads as drifted, and none of them has changed

Drift is a byte comparison: the panel renders what it would push now and compares that
against the digest of what it last pushed. A comment is bytes, so the one reworded
comment above is a difference. **The moment the new image is up, every node carrying a
WireGuard-family transport reads as out of sync, before anybody has touched anything.**
The Overview says *"Not yet pushed to `<node>`: that node is not running the
configuration this panel would give it"*, and the Nodes screen counts that row among the
drifted ones. A node whose transports are all VLESS is unaffected — its rendered document
did not move at all.

**On screen that is indistinguishable from a real configuration change**, and it arrives
at the one moment you are watching for trouble. It is not one, and no user is affected
while it stands: the config already on the device keeps working, because the line that
moved is one `wg-quick` never reads. Apply each of those nodes on the Nodes screen — an
ordinary apply, nothing special about it — and the count goes back to nothing.

**Expect it again, in the same shape, if you roll back.** Going back to the old image
re-renders the old comment, so every one of those nodes drifts a second time and needs
the same pass of applies.

### The two migrations, and how to go back

The container applies them itself: `deploy/docker/entrypoint.sh` runs `alembic upgrade
head` on every start, so bringing the new image up **is** the upgrade. Two revisions land.

- **`0008` renames, and only renames.** The table `friends` becomes `users`, both
  `friend_id` columns become `user_id`, and the indexes and constraints that carried the
  old name follow. No row is read or written and no encrypted column is opened, so it
  cannot fail on data and it cannot touch a token.
- **`0009` rewrites two stored words an operator reads back.** A transport's `purpose`
  goes `friends` → `users`, and two audit actions go `friend-added` / `friend-revoked` →
  `user-added` / `user-revoked`. Any other value in either column is left exactly as
  found. **`purpose` is handed back verbatim by the API**, so a consumer matching on the
  literal `friends` silently matches nothing from here on.

Both reverse exactly, and the round trip has been run against a copy of real data — and
so has the rollback below, on real hosts. **The order is the whole of it: downgrade under
the NEW image, stop the container, and only then put the old tree back.** The other order
does not work, cannot be recovered in place, and takes the delivery endpoint down while
it fails — *Do not roll the image back first*, below.

On the control-plane box:

```bash
# 1. Downgrade under the image that is still running. It is the only image that has
#    0008 and 0009 in it, and therefore the only one that can undo them.
docker compose --env-file .env -f deploy/docker-compose.yml exec control sh
# --env-file is not optional: without it every ${VAR} becomes an empty string and
# nothing says so.

# inside the container. alembic.ini ships inside the installed package, which is how
# the entrypoint finds it too — there is no checkout in that image to point at.
INI=$(python -c 'import control, pathlib; print(pathlib.Path(control.__file__).parent / "alembic.ini")')
alembic -c "$INI" downgrade 0007    # Running downgrade 0009 -> 0008, then 0008 -> 0007
alembic -c "$INI" current           # 0007
exit

# 2. Stop it, before anything can carry the schema forward again. `stop`, not `restart`
#    and not `down` followed by an `up`.
docker compose --env-file .env -f deploy/docker-compose.yml stop control

# 3. Put the old tree back in the checkout, then bring the stack up on it. That image's
#    entrypoint runs `alembic upgrade head` as always, but ITS head is 0007, so the
#    upgrade is a no-op and the panel comes up on the schema you just rolled back to.
git checkout <the commit or tag that predates this release>
make up-panel
```

**A schema rollback does not survive a restart, and that is why step 2 is a step.** That
`alembic upgrade head` in the entrypoint is unconditional and runs on *every* boot, so a
database left at `0007` under the new image is carried forward again by the next
`compose up`, the next `restart` and the next reboot of the host — with nothing to read
but two lines in the container log. Check `select version_num from alembic_version` when
you are done rather than assuming.

**Do not roll the image back first.** The old image ships `0001`–`0007` and nothing else,
so it holds no downgrade path from `0009` and cannot take the schema back for you. Its
entrypoint dies on `Can't locate revision identified by '0009'`, and `restart:
unless-stopped` makes it do that for as long as you leave it. Measured, in that state:

- the control container crash-loops, logging `applying migrations…` then
  `FAILED: Can't locate revision identified by '0009'`, over and over;
- `make up-panel` exits non-zero with `dependency failed to start: container
  hashi-control-1 is unhealthy`, and **Caddy never starts at all** — it sits in
  `Created`;
- so `/sub/{token}` refuses the connection for **every** user, from the first second of
  that state until you are out of it. That is the one route the whole design says stays
  up;
- and you cannot `exec` in to fix it, because `docker compose exec` on a restarting
  container answers `Container … is restarting, wait until the container is running`.
  The commands above are not available to you there.

Getting out of it is putting the new image back, doing step 1 under it, and continuing
from step 2 — the order above, arrived at the expensive way.

**Ask `alembic_version` that same question *before* you upgrade.** Because the upgrade is
unconditional and silent, a control plane sits at whatever revision its image last
carried — this project's own was **seven revisions behind** its repository when it was
measured, having been up since long before these two existed. The jump one container
start makes is from what `alembic_version` actually says to head, which may be a good
deal more than the two migrations above.

**Take a backup first** (*Backups*, below), and keep `HASHI_SECRET_KEY` where the dump is
not. A restore under the wrong key is not a broken migration and must not be read as one:
every screen that loads a user or a node answers *"The data is intact; the key is wrong.
Nothing has been changed."*, while a migration fault fails at the driver first, on an
undefined table or column.

---

## Moving the delivery endpoint, and what users have to be told

**Moving delivery is an out-of-band event. Work out what your channel is before you need
it, because the one channel this product has is the thing that stops working.**

A subscription link names a host. The link every user holds today is this control
plane's — `https://<HASHI_PUBLIC_HOST>/sub/<their token>` — and it does not move: it is
the same string for the life of that subscription, wherever the fleet goes. A **delivery**
link is a different thing. A host that answers its own users' refreshes answers under
**its own name**, on a path derived for that host alone, so a delivery link is a *second*
link and not the same link served from somewhere else. Change which host serves delivery
and every delivery link already handed out is dead — there is no record you can move to
save it, and no message this product can send to say so, because the only address it
could send one to is the one that just died.

**So it works if you move *before* a block, and it is impossible if you move *because* of
one** — which is exactly when you will want to. That is the limit. It is stated here
rather than engineered around: the alternative considered and rejected on 2026-09-27 was
issuing every subscription with several delivery links to fall back between, which
doubles the places a credential can be recorded, puts a Russian host's address into a
foreign host's artifact and the reverse, and does not answer the case anyway — those
links, too, have to be handed out before the block. See `docs/decisions.md` for the whole
of that argument.

### What is true today, before you plan around it

**This panel hands you no delivery link.** The Nodes screen tells you that a host is
answering refreshes and under which name, and it states how long the certificate it is
holding has left. It does not compose a link for a particular person, and nothing else
here does either.

So nobody is holding a delivery link yet, and until something hands them out, moving
delivery costs a user nothing: you enable or withdraw transports, press **Apply**, and
which hosts hold a listener follows from that. It is derived from what the fleet already
knows — there is no setting for it, and there is nothing to switch off on the hosts that
should not have one.

### Every delivery link you ever hand over travels with this sentence

> Add this link to your app alongside the link you already have — do not replace it. It
> is answered by one server and carries only what that server can give you, so an app
> left holding this one alone loses everything the other link still has in it, and that
> looks exactly like being cut off.

**This is not advice, and it is not optional.** A delivery host serves a **slice**: the
material it holds is its own users' configurations for *that host*, and nothing from any
other node in the fleet — deliberately, so that seizing it yields no other node's address.
A client that *replaces* its subscription with a delivery link therefore loses every node
the person holds anywhere else, silently, in a way they cannot tell apart from having been
cut off. The document itself cannot warn them: a truthful warning would have to say
whether *that person* has nodes elsewhere, and writing that onto the most seizable machine
in the fleet gives a seizer more than the addresses were hidden to withhold. The sentence
above is the whole of the protection, and it only works if it goes with the link every
time.

Send it word for word. The panel shows you the same sentence on the row of any host that
is answering, so you can copy it from there; it is one string in the product, and
`tests/infra/test_deploy_runbook.py` fails if this copy and that one part company.

### When a delivery host stops being one

1. **Do it before you have to.** A host you are decommissioning, replacing or moving out
   of the country is a planned move; a blocked one is not, and by then the people you
   need to reach are the people who cannot reach you.
2. **Reach every user holding a link on that host, through a channel that is not this
   product.** Whatever you already use to hand someone their first link is the channel
   this depends on — this runbook cannot choose it for you, and the product has none.
3. **Tell them three things:** the old link is dead and can be deleted; here is the new
   one, if there is one; and add it *alongside* the link they already have, in the words
   above.
4. **Nobody is left with nothing**, and that is what makes this affordable rather than
   merely cheap. Because a delivery link is only ever *added* to the one they already
   hold, a user whose delivery host disappears still has the control plane's link in
   their app and keeps working — as long as they can reach this control plane. Which is
   the state the whole fleet was in before delivery hosts existed, and is exactly the
   state delivery hosts exist to improve on, so **do not treat it as a reason to delay
   step 1**: under a shutdown, that fallback is the thing that is unreachable.

**And take the material off the host, which an apply does for you — in the states it
reaches.** A delivery host holds what *Which host answers a refresh* lists: its users'
rendered subscriptions (a WireGuard-family archive carries the user's client `PrivateKey`),
the fleet's wildcard key and the site that serves them, under `/opt/hashi`. **An apply
that finds a host is no longer a delivery host takes all of it away** — whatever the
reason it stopped: its last user-facing transport withdrawn, its `address` changed to an
IP, the certificate removed or expired, or the control plane now on that box. That holds
for the apply the panel refuses too: withdrawing a host's last transport and pressing
**Apply** answers that there is nothing to apply, and still takes its delivery material,
the site and the key back first. That refused apply places no compose file, so the
listener's container stays up with nothing left to serve until the next apply on that
host succeeds. So the order for a host you are dropping is **withdraw its user-facing rows,
Apply, and only then retire the node** (its state, on the Nodes screen) — a retired node is
one the panel will not let serve again, which no apply reaches (below), so the apply has to
come first. There is no way to delete a node record.

Three states no apply reaches, and in each the material stays on the host until you remove
it yourself:

- **a node the panel will not let serve again** (retired) — the Nodes screen already says nothing
  from here reaches that host, and the way back is a new record;
- **a node that is not serving when a user is revoked** — the revocation applies only to
  nodes in service, so a degraded or draft host keeps that user's rendered subscription
  until it is repaired and applied;
- **a node whose record is gone** — removed from the database by hand, or lost with a
  database restored from a backup older than it: nothing here knows the host exists.

By hand, on the host, as the account it was driven as:

```bash
rm -rf /opt/hashi/delivery /opt/hashi/delivery.incoming /opt/hashi/delivery.replaced \
  /opt/hashi/delivery-site.Caddyfile /opt/hashi/delivery-cert.pem /opt/hashi/delivery-key.pem
```

A host no apply can reach — behind a closed border, or seized — keeps everything it was
last given, and what that yields is recorded in `docs/decisions.md` (the seizure inventory
of 2026-09-27).

---

## Rules that are not optional

- **Never plain WireGuard on the entry→leaf hop.** That hop crosses the border by
  definition, and a protocol-blocked transport there defeats the topology even in phase
  1. Use AmneziaWG or another obfuscated transport. This one is enforced rather than
  advised: the hop form offers only the transports that can carry a hop at all, which
  in this image is `amneziawg` and nothing else.
- **Never present plain WireGuard to a user as something that works from a Russian
  mobile network.** TSPU protocol-blocks it. It works everywhere else.
- **A decoy host is chosen per node and never shared.** There is no project default and
  there must never be one — if every node borrows the same handshake, the fleet becomes
  enumerable by that fact alone.
- **A node may run one transport twice. What it may not do is run it twice on one
  port, under one config name, or over one tunnel range.** Two rows on one node collide
  on three things. The **listening port** — with its protocol, so a TCP transport and a
  UDP one on the same number are two sockets and no conflict. The **config name**, which
  for the wg-quick family is also the interface name. And, for the WireGuard family, the
  **tunnel range**: two such rows on one node may not have overlapping tunnel networks,
  hop ends and disabled rows included. That third one is refused in the panel, under the
  box you typed it in, before anything is saved:

  > node `E` already carries `amneziawg` on a tunnel at … and … *is in the same range.
  > Two tunnels on one node cannot share one: their data planes write into that host's
  > single routing table, so a reply meant for one person's device would be sent to
  > whoever holds the same address on the other — and neither config file shows it,
  > because each is correct on its own. Give this tunnel a range of its own.*

  Overlapping is not only the same range typed twice: a range you widen on one row
  swallows the narrower one beside it, and that is the pair written by accident. This
  is the rule that meets you when you install on one box and then build a hop from
  that same box — users and hop are two `amneziawg` rows on that node, and they need
  two ranges as much as they need two ports. A **disabled** row still holds all three,
  because freeing them would move the collision to the moment somebody switches it back
  on; removing the row is the only thing that gives them back.

  **And one thing on a node that is not a row at all collides too — TCP 443, on any host
  that carries a user-facing transport and is registered under a name, while this control
  plane holds a usable delivery certificate** (*The delivery certificate*, above). That
  host answers its own users' subscription refreshes, which is what makes a refresh work
  while this control plane is behind a closed border, and the endpoint has to be on the
  port an ordinary HTTPS client reaches. So the panel refuses a transport there, under
  the box you typed it in:

  > node `E` answers its own users' subscription refreshes on TCP port 443, so no
  > transport on it can hold that port. *…Give this transport another port — and weigh
  > what that costs here, because a TLS transport answering on an unusual port is itself
  > a signal.*

  **Read that cost before you plan an arrangement around it.** It is `vless-reality` this
  usually refuses, and Reality's whole camouflage is being on 443 — so an entry node that
  serves its own users' refreshes cannot also be a website on the ordinary port. That is a
  real loss and it was taken knowingly, on 2026-09-27: the alternative put the refresh
  endpoint behind the same name the tunnel hides under, so that blocking one name killed
  both at the same instant — in exactly the arrangement the endpoint exists for. A host
  with no user-facing transport, or one registered by IP address, keeps 443 for its
  transports, because neither answers a refresh — and so does every host while both
  `HASHI_DELIVERY_*` paths are blank, the shipped default, because then no host answers
  one. On the control plane's own box the refusal can fire too, when that box is
  registered under a name: no listener goes there, but the control plane's Caddy already
  holds 443 on it, so the refusal is true for a different holder.

  Nothing else collides.
- **A user-facing kernel tunnel and the hop a node DIALS still cannot share that
  node**, which is a different rule and the one that bites — *The one combination that
  will not render*, above. **Which end of the hop it is decides the answer**, so this
  rule is never absolute: on the **leaf** end the same two rows are ordinary and
  supported. A leaf's users exit by the leaf's own route, a hop landing there does not
  change that, and one box carries `amneziawg` for its users and `amneziawg` for the
  leaf end of the hop with both enabled — two ports and two ranges apart, exactly as the
  rule above requires. It is the node that dials the hop that may not also hand one to
  its users. That asymmetry is what makes *Growing out of one box*, above, possible at
  all.
- **A WireGuard-family row is told how many users it may serve, and the number is a
  ceiling.** AmneziaWG and plain WireGuard give every user their own address inside the
  tunnel, drawn from a pool that starts at the row's `peer_tunnel_address` and is as long
  as the `pool_size` you set when you enable it. One address is one user. A pool smaller
  than the people you already have is **refused before anything is saved** — at enable,
  when you add a user, when you offer the transport again, when you put the node into
  service and when you resize it — and the panel says so on the screen rather than after
  the press: Keys & configs shows `<users> of <pool>` per row, the add-user dialog names
  a pool that is full and offers no button, and a node whose pool is short is not offered
  the serving state. Resize on **Keys & configs → replace params**; there is no other
  action for it. VLESS transports identify each user by their own material and have no
  pool at all.
  *Until M17 these rows minted one shared address, so the second user on a node
  collided on `AllowedIPs` and the render refused, loudly — backlog item 33. A row
  enabled before that upgrade has no size, hands out exactly the one address it renders
  today, and is repaired by replacing its parameters with a size: the address the working
  device already holds is written down first and is never moved.*
- **Never edit anything under `/opt/hashi` on a node — with one exception.** It is
  generated by the control plane and overwritten on every apply. The control database is
  the source of truth, and that is what makes replacing a node safe. The exception is a
  **rendered config whose transport is no longer enabled** on that node — `.conf` for the
  WireGuard family, `.json` for the VLESS pair, since the extension is the transport's:
  nothing regenerates it, so the reason above does not reach it, and what it holds is the
  node's private key and every user's credential for that transport. Delete those, after
  the apply that removed the service — see *If you already built it the other way*, above.
  Delivery material is not an exception: an apply takes it away whenever the host stops
  being a delivery host, and the states it cannot reach are listed under *When a delivery
  host stops being one*, above.

## Known-unproven

`docker.io/masipcat/wireguard-go:0.0.20230223` has a tag that resolves but has **never
been started by this project**. Whether it accepts `up <config>` as its command is
discovered on your first real node. If it does not, that is a finding, not a mistake on
your side.

Every other data-plane image pin is checked against a real registry by
`tests/e2e/edge/test_every_image_pin_resolves.py` — a check that exists because one pin
in the tree turned out never to have existed at all.

**This project has never re-issued a certificate on a replacement host.** The reasoning
in *Backups* for not keeping `caddy_data` rests on issuance being automatic and on the
CA's published rate limits, both read rather than observed. The first real rebuild is
what turns that into a fact; if it does not go that way, that is a finding.

**No delivery host has served a real user from a real host.** An entry answering its own
users' refreshes — the C+L | E and C | E | L rows of *Where the three roles go* — has run
on the disposable stand only, which can show what is placed, served and recorded and cannot
show a border. Whether a refresh from inside Russia reaches it while the control plane is
unreachable is a field observation nobody has made yet. The arrangement walked on real
hosts is C+E | L (2026-10-02), where no delivery host exists by construction.

**The Bot API has never been polled from a Russian entry box.** The owner's Telegram bot
(*Adding a user from Telegram*, above) is the `telegram-bot` container dialling
`api.telegram.org` from the entry box — and reaching that address from there is the border
this fleet exists to cross. The route the bot is meant to take, out through a leaf, is the
leaf egress of M40, which has not landed; until it does, expect the `polling is failing`
WARNING on the real host and no command answered, with the panel and delivery unaffected.
The stand runs the whole loop against a fake Bot API (`.e2e/profile.yml` lists `telegram`
under `stubbed`), which proves the bot composes beside the real control plane and says
nothing about a border. `make logs PROFILES=telegram-bot` is what shows which line it is;
`HASHI_TELEGRAM_API_URL` is where a relay you run yourself would go if you build one before
M40 — but the route M40 adds is the fleet's own answer, not a mistake on your side.

## Backups

```bash
make backup                                       # → backups/hashi-<timestamp>.sql.gz.age, mode 0600
make backup-upload FROM=backups/hashi-<...>.sql.gz.age  # send one that is already written
HASHI_RESTORE_AGE_IDENTITY=/path/to/identity \
  make restore FROM=backups/hashi-<...>.sql.gz.age  # destructive, so the path is required
make restore-from-bucket                          # the whole rebuild, on a machine that
                                                  # has never run this — see below
```

`make restore` is destructive and never picks "the latest one" for you: it is given a file
you are already holding, and choosing between files you can see is not a decision a
Makefile gets to make. `make restore-from-bucket` is the other case and does choose,
because there the artifacts are in a bucket you cannot see into at all and the alternative
is a restore that cannot be started — see *Coming back from the bucket, on a machine that
has never run this*, below, for how it chooses and what it prints.

**The file `make backup` writes is encrypted, whole, before it reaches the disk.** It is
`age` ciphertext, addressed to the public key in `HASHI_BACKUP_AGE_RECIPIENT`, and this
host holds only that public half: it can write a backup and **cannot read one back**. The
plaintext exists nowhere but in memory, in flight, while the dump runs — it is never a
file on this machine, not even briefly, so there is no moment at which a seizure catches a
plain copy on the disk.

Under the `age` layer it is plain SQL, gzipped, in which a *subset of columns* is
encrypted again — every node's `ssh_private_key`, every node_transport's `secrets`, every
user's `token`, `subject`, `secrets` and `tunnel_address`. **Opening the artifact and
reading it are two different secrets:**

1. the **age identity**, the private half of the keypair, which opens the file;
2. **`HASHI_SECRET_KEY`**, without which those columns cannot be restored.

Neither is on the control host, and that is the whole point: a seizure of this machine
hands over every backup it ever wrote and opens none of them. Keep the two apart from each
other as well — a copy of both in one place means one theft takes everything.

What a reader of the bucket learns, and the jurisdiction that bucket sits in, is written
down in `docs/decisions.md`. In one line: that a backup exists, how big it is and when it
was written — not a node address, not a leaf address, not how many users there are.

**Generating the keypair**, once, on a machine that is not the control plane:

```bash
age-keygen -o hashi-backup-identity.txt   # prints the public key; keep the FILE with you
```

The public key it prints goes in `HASHI_BACKUP_AGE_RECIPIENT` in `.env`. Until it does,
`make backup` refuses and says so. It will not write a plain artifact as a fallback,
because a fallback is how the plain shape survives.

**Restoring.** The identity is handed over at the moment of the restore, from whatever you
are carrying, and never written into `.env` on this host:

```bash
HASHI_RESTORE_AGE_IDENTITY=/path/to/hashi-backup-identity.txt \
  make restore FROM=backups/hashi-<...>.sql.gz.age
```

**What it asks before it replaces anything**: it names the env file, the compose project
and the database it resolved, counts what is in that database, and asks you to type the
database name — *unless there is nothing there*, in which case it says so and asks
nothing. A database with rows in it and no terminal to answer on is a refusal with a
sentence, not a silent exit; `FORCE=1` is the deliberate way past.

**What it says afterwards** (M31.6, M31.8, M31.9 — one account, the same in both restore
commands): how many nodes and users the restored database now holds, and a warning in so
many words when that is none — an artifact older than the fleet looks exactly like a good
one otherwise. Then it **restarts the control plane itself** and waits for it to be
healthy: the dump drops and recreates every table, and the control plane's database
driver caches statements per connection against the tables that were dropped, so a
restart is what makes the first requests after a restore not fail. It is `restart`, which
changes nothing about what this host publishes — **not** `make down && make up`, which
would take every published port away. `make restart-control` is printed only if that
restart does not finish. The compose project it names in its confirmation is the one the
running database container belongs to (`hashi`, unless you set `COMPOSE_PROJECT_NAME`).

**The wrong `HASHI_SECRET_KEY` is the one failure it cannot see**, and it ends by saying
so: the rows arrive whatever the key is. Open the panel — if a node or user screen, or an
apply, answers *"The data is intact; the key is wrong."*, the fix is that one line in
`.env` and not another artifact.

`age` runs inside the control container, so nothing extra is installed on the box and any
host that can run the stack can restore. If the control plane itself will not start, open
the artifact by hand on any machine that has `age` and restore what comes out — the script
still accepts that shape:

```bash
age --decrypt --identity /path/to/hashi-backup-identity.txt <file> > hashi.sql.gz
make restore FROM=hashi.sql.gz
```

**A backup taken before 2026-09-23 still restores.** Plain SQL, gzipped, is what
`make backup` wrote until then; `make restore` takes it as-is and needs no identity. It
tells the two shapes apart by reading the file rather than trusting its name, and says
which one it found before it touches anything. Those older files are **not** safe offsite:
they are a map of the fleet to anyone who opens them, with every node's real address,
including the leaf addresses no user is ever shown. Keep them on media you control, and
replace them with a fresh backup at the first opportunity.

### Coming back from the bucket, on a machine that has never run this

The day this is used is the day the box is gone. What you have is a bare machine, this
repository, and three things you are carrying. One command does the rest:

```bash
# the runtime first — a genuinely bare host has none of docker, make or bash; see
# "What every box must already have" above. This command does not install one for you.
# Then the code, from your own machine: "Ship the code to the control-plane box" above.
cd /opt/hashi-control
cp .env.example .env

make hash-password      # prints the whole HASHI_OPERATOR_PASSWORD_HASH line to paste in.
                        # It runs inside this project's control image, so this host needs
                        # nothing but the runtime it already has.

# then fill in .env: HASHI_SECRET_KEY, the hostnames, that hash and the database
# password. That is what the control plane needs in order to START; where the BUCKET is
# is the next four lines, and it is not in .env on a machine that has never run this.

HASHI_RESTORE_AGE_IDENTITY=/path/to/hashi-backup-identity.txt \
HASHI_RESTORE_S3_ENDPOINT=<your store's own endpoint, with a scheme> \
HASHI_RESTORE_S3_REGION=<its region> \
HASHI_RESTORE_S3_BUCKET=<the bucket these backups are in> \
HASHI_RESTORE_S3_PREFIX=<the key prefix, if you set one> \
HASHI_RESTORE_S3_ACCESS_KEY_ID=<a key that may list and get> \
HASHI_RESTORE_S3_SECRET_ACCESS_KEY=<its secret> \
  make restore-from-bucket
```

That installs the control plane on this machine, reads the bucket, takes the newest
artifact that actually opens, and restores it. It is safe to run again after any failure —
with one exception on a host that is already serving, three paragraphs down.

**Why the four `HASHI_RESTORE_S3_` lines that are not credentials are there.** Endpoint,
region, bucket and prefix fall back to the `HASHI_BACKUP_S3_` block of `.env` — the right
default on a host that was taking backups, because that is where they already are. On a
machine rebuilt from `.env.example` that block is **the template's example store**, which
belongs to nobody: the walk of 2026-09-23 followed this section exactly, installed the
whole control plane, and died at a hostname out of the template with `Name or service not
known`. So either fill those four into `.env` beside the rest, or hand them to the command
as above. Either way the command **prints which of the two each value came from** before
it asks the store anything, so a value that came out of the template is visible before the
failure rather than after it. The two credentials never fall back to anything: the key in
`.env` may only write, and reaching for it silently would turn the clearest refusal there
is into a 403 that reads as your own key being wrong.

**`make hash-password` is here because the value could not be made on the machine that
needs it.** The hash is a scrypt digest produced by this project's own code, so the
documented route — `python -m control.cli hash-password` — needs the project installed and
Python 3.14. A host rented an hour ago has the system's Python (3.10 on Ubuntu 22.04) and
`make setup` cannot make a venv it does not have an interpreter for. Until this target
existed, one of the four values above required a **second working computer**, in the
middle of a rebuild: the walk of 2026-09-23 met it as a traceback, then a
`command not found`. The image the target builds is the same image the restore builds
seconds later, so it costs nothing the rebuild was not already spending.

**A terminal, or `FORCE=1`.** The restore replaces live data and confirms before it does,
and a confirmation needs somewhere to be answered. On a machine this command has just
installed from nothing there is nothing to confirm — the database holds no rows and it
says so instead of asking — so the ordinary bare-host run needs no terminal at all. If the
database does hold something and there is no tty (`ssh host 'make …'`, a wrapper, a cron
entry), it stops **before the bucket is read** and says so, rather than printing a question
into a session that cannot answer it. `FORCE=1` skips the question and nothing else.

**It dials no node until you publish.** A control plane rebuilt from the bucket comes up
with the re-measure loop held at `HASHI_FINDING_REMEASURE_INTERVAL=0` (M31.2): the restored
database may hold nodes carrying a finding, and probing them on a timer from a machine
nobody has looked at yet is not something to do on its own. The closing screen says whether
the hold took. Publishing (`make up-panel` / `make up-panel-over-ssh`) recreates the
control plane with the value in `.env` — blank is every 60 seconds — so to keep it off
afterwards too, put `HASHI_FINDING_REMEASURE_INTERVAL=0` in `.env` before you publish. The
same line stops it on any control plane: change `.env`, then run your publishing command
again (a `make restart-control` alone does not re-read the env file).

**Then publish the ports, and mind which command.** The command ends by naming them; the
one to use on a freshly restored host is `make up-panel-over-ssh`, because `make up-panel`
wants `HASHI_PRIVATE_BIND_ADDR` to be a management-tunnel address this machine does not
have yet. See *The port-publication gap*. The closing screen prints the `ssh -L` line with
this deployment's own console port in it, read out of the running stack rather than left
for you to find in `.env`.

**"Safe to run again" is true of the data and false of the publication, on a host that is
already serving.** The install step converges the stack to the base compose file, which
publishes nothing — so re-running this (or `make panel-bootstrap`) on a host where
`make up-panel` had published 80, 443 and the console takes all three away until you
publish them again. Nothing is lost but reachability, and the database is untouched. The
bootstrap now **says so before it does it and again when it has finished**, having asked
the running stack what it publishes, so this paragraph is a second place rather than the
only one.

**No management tunnel is generated from the template's own values.** `.env.example` ships
a complete `HASHI_MGMT_*` block, and a machine rebuilt by copying that file arrives with
one. Generating a tunnel from it wrote a config here and printed a **full device config,
private key included**, for each of the template's example devices, pointing at the
template's example endpoint — credentials nobody asked for, for a host that is not this
one. The bootstrap compares the block against `.env.example`'s own line and skips the
generation, saying which mode it left the host in; fill the block in with this
deployment's values and run it again to get a real one. See *The management tunnel*.

**And the restored host is not backing anything up.** `HASHI_BACKUP_AGE_RECIPIENT` and the
write-only `HASHI_BACKUP_S3_*` credential lived only in the `.env` that was lost — that
file is deliberately in no backup — so `make backup` here refuses outright with
`required variable HASHI_BACKUP_AGE_RECIPIENT is missing a value`, and the crontab that ran
the schedule was on the old machine too. Put the **public** half of the age keypair you are
carrying back into `.env`, refill the S3 block, and run `make backup-schedule`. The command
says this on its last screen as well, and says which of the two cases it measured. Until
you do it, the fleet has exactly one copy of itself and it is the machine you just built.

**It does not move DNS, it does not re-issue the delivery endpoint's certificate, and it
tells no user anything** — the three that decide whether a restored control plane serves
anybody. They are the section immediately below, and the command says them again on its
last screen.

**`HASHI_SECRET_KEY` goes in `.env` here; the other two never do.** That is not the design
leaking — it is where the design puts it. The control plane cannot start without that key
and cannot read one node or user credential without the *right* one, so it belongs in this
machine's own env file exactly as it belonged in the lost machine's. What must never be
written onto a control-plane host is the **age identity** and the **read credential for the
bucket**: those are `HASHI_RESTORE_*`, they are handed to the command in its environment at
the moment it runs, and the command reads them from there and nowhere else. Putting them in
`.env` is not a working shortcut — it refuses, and says where they belong.

**Which object it takes.** It lists everything under the prefix, prints the newest ten with
the store's own timestamps, and takes the newest. The order is the **store's**
`LastModified`, not the object's name: the name is chosen by whichever key wrote the
object, and on a live control plane that is a key an attacker would hold. If the newest
does not open, it says so and walks back — up to five — and each attempt names what was
wrong with the one before it. `make restore-from-bucket OBJECT=<name>` takes exactly the
one you name and does not walk.

Unlike `make restore`, this one *does* choose for you, and the difference is the point:
`restore` is given a file you are holding, and here you cannot see into the bucket at all.
What it chose is printed beside everything it did not choose.

**The artifact opens before anything is asked of you.** It is decrypted and checked to be a
whole gzip stream *before* the destructive confirmation, so nobody types a database name to
authorise a restore that was always going to fail. Every object it fetched is left in
`backups/`, mode 0600, still encrypted.

**What each failure says, because at 3am "it did not work" is the difference between five
minutes and an hour.** Every one of them names which of the three inputs is wrong:

| What is wrong | What you get |
|---|---|
| No container runtime, no compose plugin, or a daemon that is not answering | Three different sentences, each naming which one, and *"Nothing has been fetched and nothing has been changed"*. `git` and `make` cannot be the problem here — they are what put this checkout on the machine and what ran the command |
| No `.env` | The copy-and-fill line, `make hash-password` for the value that cannot be typed, and why that file is deliberately in no backup |
| The env file is one compose cannot parse | The file and the line number, never the line — see *When the backup runs* |
| `HASHI_SECRET_KEY` missing from `.env` | The bootstrap refuses before anything is built, and never generates one |
| `HASHI_OPERATOR_PASSWORD_HASH` missing, or still `.env.example`'s placeholder | The bootstrap refuses at once and names `make hash-password`, rather than letting the control plane refuse the unfilled value three minutes later as a health-check timeout |
| No terminal to confirm on, and a database with something in it | Said **before the bucket is read**, with what it counted and with `FORCE=1`. A database this command just installed holds nothing and is never asked about |
| `HASHI_RESTORE_AGE_IDENTITY` unset or not a file | Named as the private half you carry, with the form to supply it in |
| The read credential is not in the command's environment | Named, with the reminder that the key in `.env` may only write and is not the one to reach for |
| Endpoint, region or bucket unresolvable | Every missing name at once, and that three of them may come from the `HASHI_BACKUP_S3_` block instead |
| The endpoint is set, and it is the template's | Before anything is asked of the store, the command prints the endpoint, the bucket and the prefix it is about to use **and which name each came from** — its own, or the `HASHI_BACKUP_S3_` fallback in `.env`. If the store then cannot be reached, the refusal names that same value rather than leaving a DNS error to be read as a network fault |
| The store refuses the credential | *"A restore needs a credential that may LIST and GET this bucket"* — the write-only key produces exactly this, and it is the most likely mistake on the list |
| No such bucket | Named as the bucket and not the key, because the credential answered |
| Nothing under the prefix | *"The credential works — this is the bucket or the prefix"* |
| The identity is not the one these artifacts were written to | *"The artifact is intact; the identity is wrong."* It stops rather than walking the history: every object was written to the same public half |
| The newest artifact is damaged | Says what did not open, and tries the one before it. Five, then it stops and tells you to name one |
| The restore itself fails part-way | The database is left exactly as it was — one transaction, `ON_ERROR_STOP` — and the artifact is still in `backups/` |
| The artifact is older than the fleet | The restore succeeds, and says *"That is NO nodes and NO users"* beside the counts, and again on the last screen with the `OBJECT=` line to name an older one |
| `HASHI_SECRET_KEY` is the wrong one | **Nothing.** The restore succeeds: the rows arrive whatever the key is, and the columns holding node and user secrets stay shut. This is the one failure the command cannot see, so it ends by naming it — open the panel, and if a node or user screen, or an apply, answers *"The data is intact; the key is wrong."*, it is that one line and not another artifact |

### What `make restore-from-bucket` does not do

Everything on this list is an operator step. None of it is something a script may do on
your behalf, and all of it is the difference between a control plane that is *back* and one
that *serves somebody*.

1. **It does not move DNS.** Nothing in this repository touches a record. Your delivery
   name still points at the machine you lost, and until it points at this one, every user's
   link resolves to a box that is gone — the tokens are alive and the address is not. This
   is the one that leaves a perfectly restored control plane serving nobody.
2. **It does not re-issue the delivery endpoint's certificate.** `caddy_data` is
   deliberately not in the backup (see *What belongs in a backup, and what does not*): the
   old host's private keys are to be presumed compromised. Caddy asks a public CA for a new
   one only once `make up-panel` (or `make up-panel-over-ssh`, on a host with no tunnel
   yet) publishes `:80`/`:443` — the stack this command brings up publishes neither and
   asks no CA anything (M31.1) — and the request succeeds only once the name resolves
   *here*, which cannot happen before 1. **Do 1 first, then publish**: a publication
   whose name still points at the lost machine fails validation, and each failure counts
   against the live domain's rate limit. Until then `/sub/*` serves nothing.
   The panel itself is unaffected: it is served by Caddy's own CA, which is new, so each of
   your own devices is asked to trust the console once more. The costs and the issuance
   limits are in *The `caddy_data` cost, stated rather than waved at*.
3. **It tells no user anything.** No message goes to any user from this command or from the
   control plane — there is no channel, and that is a charter decision rather than an
   omission. If the delivery *name* is gone rather than merely pointing elsewhere, the
   tokens survived and the URL they live in did not, and every user has to be handed a new
   link by you.

It also does not tell you whether `HASHI_SECRET_KEY` is the right one, and cannot: see the
last row of the table above.

### Where the artifact goes, and the credential that sends it

With `HASHI_BACKUP_ENABLED=1` **in `.env`**, `make backup` sends the artifact it has just
written to the object store configured in the `HASHI_BACKUP_S3_*` block of the same file:
one `PutObject` to
`<endpoint>/<bucket>/<prefix><file>`, and nothing else. The store is addressed by the **S3
protocol, never by a provider's name** — the same rule as a node's country and address
living in a node record rather than in code, and for the same reason: a provider you cannot
rotate away from is one you are stuck with on the day you need to leave it. Moving to
another store is four lines of `.env` and no code.

**The credential kept on this host may only write.** `PutObject` and nothing else: no
`GetObject`, no `ListBucket`, no `DeleteObject`. Whoever holds this box holds that key, and
a key that can delete turns a seizure into the loss of the entire backup history as well as
the machine. That is half of the protection; the other half is enforced on the **bucket**,
where this key has no authority, and it is set up by hand when you create the bucket — see
*The retention this host's own key cannot reach*, below.

**What "uploaded" proves, exactly.** The SHA-256 of the artifact is inside the request's
signature, so a store that accepts the request has recomputed that hash over the bytes it
received; where the store returns a comparable `ETag`, it is compared against the same
bytes as well. That is a real statement about what arrived. It is *not* a statement that
the object is still there, that retention is keeping it, or that it can be read back — this
host holds a write-only credential and cannot look, which is the whole point. The only way
to verify a backup is to restore it, from a machine that holds the identity, which is the
part of this section above.

**When the upload fails, the dump does not fail with it.** The artifact is here, intact and
encrypted, and `make backup` exits **3** rather than 0 — a code of its own, because "there
is no backup" and "there is a backup and it never left the machine" call for different
actions. Send the same file once the store answers again:

```bash
make backup-upload FROM=backups/hashi-<...>.sql.gz.age
```

Nothing is dumped a second time, and the database is not touched. Use `https`: over plain
`http` the key id and the name of your bucket travel in the clear, and the upload refuses
unless the endpoint resolves to a private address.

**In the env file, and nowhere else.** `HASHI_BACKUP_ENABLED=1 make backup` on the command
line does not switch the upload on: two things read this value — the uploader, and the
thing that writes the backup record — and until M28.15 an exported one reached only the
first, so a run uploaded the artifact and `make backup-status` then said the upload was
switched off, about that same run. One file both of them can see is what stops that.

`HASHI_BACKUP_ENABLED=0`, or unset, is a supported mode rather than an oversight — the
artifact is written and stays on this host, and every run says so in as many words. It does
not switch the **schedule** off: a daily backup that never leaves the machine is still a
backup, and the section below keeps taking it. What still does not exist is a place for the
management directory inside the artifact (see *What belongs in a backup, and what does
not* — the artifact is the database and nothing else so far).

### When the backup runs, and how you know it did

```bash
make backup-schedule      # install it: one cron entry, no root, nothing new on the host
make backup-status        # when did one last succeed, and has one failed since
make backup-unschedule    # stop it
```

**Set the hour first**, in `.env`:

```ini
HASHI_BACKUP_AT=04:00
HASHI_BACKUP_TZ=Etc/UTC     # an IANA zone NAME — `Europe/Paris`, `Asia/Tokyo` — never an offset
```

`HASHI_BACKUP_AT` is a wall-clock time **in that zone**, and the zone is spelled out
because this host's clock is UTC and you are not. A name rather than `+02:00`: an offset is
a decision taken once about a rule that changes — by season, and by decree — and on the day
it changes, nothing anywhere tells you. Get it wrong in any of the three ways and the
backup still happens: an unset zone falls back to this host's own clock and is recorded as
`unset` (there is no correct country to guess at), a zone this host has never heard of is
recorded as `unknown`, and a time that is not `HH:MM` falls back to `04:00` and is recorded
as `malformed`. A typo must not cost you a day of backups; it costs you a line in
`make backup-status` until you fix it.

> The zone is **checked against this host's zone database, not trusted**, because
> `TZ=Nowhere/Useful date` does not fail — it answers in UTC and exits 0. A misspelled zone
> would otherwise be indistinguishable from a working one, which is the silent skew the
> variable exists to prevent.

**The cron entry carries no hour.** It runs every fifteen minutes and asks
`scripts/backup-run.sh` whether the day's backup is owed. That is the whole design, and the
reason is the failure this section exists to prevent:

> `0 4 * * *` is a promise cron cannot keep. If the box is off, asleep, or being rebuilt at
> 04:00, the minute passes and **nothing anywhere records that it did**. You find out
> during a restore.

So "today's backup has not been taken" stays true until one is taken. A box that was down
at 04:00 and came back at 10:00 takes the day's backup at 10:00 — late, and a late backup
is a backup. **The days that had none are written down by date**, and stay written down
after the next successful run; `make backup-status` and the panel both report them.
Deliberately **one** run, not one per missed day: a dump is a copy of the database as it is
now, so five runs today would be five copies of today wearing five different dates.

The first tick after `make backup-schedule` takes a backup immediately, because this host
has no record of one. That is on purpose — you learn within a quarter of an hour whether
the schedule works, instead of the morning after.

**What is recorded, and where.** `backups/state/last-run.json` on this host. It holds the
schedule's settings, the last attempt, the last success, the last failure, and the dates
with no backup — dates, exit codes and settings, **and nothing about any person**, now or
ever. The control container reads it through a read-only mount, which is how the panel can
answer *when did a backup last succeed, and has one failed since* without a credential that
could look in the bucket. Nothing on this host has one: see the section above.

**Where the panel says it.** At the top of the **Overview** — the screen `/panel/` opens on
— above the four counts, because a run that did not land has to be read without anybody
going to look for it. It says one of six things: *no backup has ever been recorded on this
host* (which is also what an empty mount says, and it means nothing recorded rather than
something broken); *there is a record and this panel could not read it*, assuming nothing
either way; *no backup has ever succeeded*; *nothing has been trying* — one succeeded, it is
days old, and nothing has failed since, which is what a schedule that was uninstalled looks
like; *backups are failing*; and a quiet muted line for a recent one. There is no colour
change between a blip and a disaster and there is not going to be one: what separates them
is the sentence — *"the last one that succeeded was 19 hours ago"* against *"43 days ago"* —
because a banner that shouts on the first failure is a banner that is ignored by the
fortieth. Every one of the six, the quiet one included, closes with a caveat saying what
it is not telling you.

**Which caveat depends on where that host sends, and this is the one thing on the screen
that is not about a run.** The record carries whether the upload is switched on, and the
panel reads it. With the upload **on**, the screen closes with *whether any of those
artifacts is still in the bucket* — the same caveat `make backup-status` closes with,
because the credential here may only write and cannot look. With the upload **off**, it
closes with *that this host is sending its backups anywhere*: nothing left the machine,
and a copy on the same disk as the thing it copies does not survive losing that disk. And
where there is no record at all, or a word the panel has no meaning for, it closes with
*whether anything was sent anywhere* — claiming neither, because it could not read which.

The middle one is the shipped default (`HASHI_BACKUP_ENABLED=0`) and it is not an alarm:
the artifact is still taken, the schedule still runs, and this is a supported mode. It is
said out loud because a caveat about a bucket, on a host that has no bucket, invites
exactly the belief that there is one.

**Two smaller things the screen now gets right, and both are about trusting the file less.**
The missed days are printed newest first — the panel sorts them itself rather than taking
the writer's order, so *"most recent"* points at now even during a gap that started weeks
ago; the writer stores them newest first as well, so the two agree without either taking
the other on trust. And the **last success** or the **last failure** in the record dated
ahead of the clock the panel reads it against is said so instead of being reported as a
backup taken minutes ago: the age is still clamped for the arithmetic, so a disagreeing
clock cannot turn a stale backup into a fresh one, but the screen goes loud with `clock
ahead` and says no age on it can be believed until the two machines agree about the time.
Those two run fields and no others — a record where only the last **attempt** is ahead
draws no `clock ahead` banner here at all, and is said on the command line and nowhere else.
(What that record's *standing* is on this screen is a separate question, answered by the age
of its runs: recent ones read as fresh, an eight-week-old last success is still loud, about
its age.) The record's `due_date` is read too, and read with a whole day of grace, so a due
date more than a day past this screen's own UTC date is loud here and one no more than a day
past is not. The Backups section below says which is which, and why that day is the width it
is.

**`make backup-status` says the same three things on the command line, out of the same
field, and refuses the same file.** It closes with whichever of the three caveats the
record's own `offsite` chooses, prints the missed days newest first, and — where the panel
says *"there is a record and this panel could not read it"* — it now says that too,
instead of printing a damaged record as fact. That was the other half of the same
finding: a record with a `schema` this script has never seen, or a `last_success` that is
not a run, was read out as *"last success: never, last attempt: never"* and exited **0**,
which is byte-for-byte what a machine that has never taken a backup prints. It exits **1**
for both of the two bad answers now, assumes nothing from the file, and names which field
it could not read — never what was in it. The line about the appointed time says that it
came from `.env` as it is **now** rather than from the record, because it does.

**Its first line is asked of the crontab, not assumed.** `scheduled:` has three answers —
*yes*, *NO — nothing on this host takes a backup*, and *NOT KNOWN* on a host with no
`crontab` for it to ask, which is the systemd-timer host above. It used to print
*"scheduled: 04:00 Etc/UTC (configured), checked every 15 minutes"* whether or not anything
was installed, including in the minute after `make backup-unschedule` answered *"removed.
Nothing runs a backup on this host now."* **When** a run would be owed is a separate line,
`appointed:`, because it has a separate source: the env file. The panel cannot make this
distinction and says so instead — it reads one record and may not go looking — which is why
the two channels word this differently and do not contradict each other.

**A record dated ahead of this host's clock is said out loud on both channels, and both
say WHICH half of it is ahead** — because the two halves cost different things. A **run**
dated after the moment the file was read makes every age printed beside it worthless: a
backup taken weeks ago reads as one taken this morning. (All three run fields are asked
here; the panel reads the last success and the last failure.) A **due date** this host has not
reached does not: the run times in that record are exact, are printed as they are, and the
age the panel puts beside them is worked out from those same times — this channel prints
the timestamp and that screen prints an age, so the two agree about the backup rather than
about a string. One paragraph covering both would tell an operator to
disbelieve a number that is right, which is the same defect one level down.
`scripts/backup-run.sh due` reports `clock=ahead` and exits **1** rather than 0 for either,
whatever the action on the same line turns out to be; `make backup-status` prints the same
paragraph and exits 0, because it is a screen rather than a verdict. `make backup` takes
one whatever the record says.

**`scripts/backup-run.sh due` refuses a damaged record too**, exit **1**, naming the key —
it used to answer `offsite=no missed=none` and *"no backup has ever been recorded on this
host"* out of a file it could not parse, which is what a genuinely fresh host prints. A
record that has merely been **re-indented** — opened in `jq`, or saved by something that
pretty-prints — is not damaged and is read normally; the layout is the only thing tolerated,
and a changed value, a truncated file or a schema from the future are refused as before. A
file **larger than 64 KiB** is refused whole, for its size, without any of it being read —
the same ceiling and the same answer as the panel, because the record is under a kilobyte
and a file that big is a wrong path rather than a long history. (The two channels are held
to that one number by `tests/infra/test_the_command_line_says_what_the_panel_says.py`,
which reads it out of both sources — and out of the sentence above — rather than keeping a
copy of it.) **Move the file aside before you go and look at it**: refusing to read it does
not protect it, and the next scheduled run writes a new record at that path over whatever
is there.

**And the schedule does not stop for a record it cannot read — it takes a backup.** All
four verbs read that file through one reader (`scripts/lib/backup-record.sh`), so `tick`
and `now` get the same refusal `due` and the panel get, and a record this host cannot parse
is treated as no record at all: a dump is taken and a new record written in its place. That
is the fail-safe direction and it is deliberate — the alternative stops the backups on the
strength of a file nothing here can understand — and `due` says which it will be, on an
`action=` line under the refusal. What it costs, stated: a host with a damaged record takes
at most one extra backup per due period until the same run rewrites the file, and a backup
taken by hand over an unreadable record does not carry the old `last_success` or the
missed-day count forward, because those are values nothing was able to check. Only a path
that is **not a file** ends in no backup, and it is refused before anything is dumped — see
below.

**And a record dated ahead of this host's clock does not stop the backups either — the
tick takes one.** That file is not damaged: every reader parses it and they all agree about
it, so it is a different state from the paragraph above and it arrives by a different road.
A host whose clock jumped forward wrote a record for a day that has not come; or
`HASHI_BACKUP_TZ` was moved west far enough to put this host back on the previous day, which
does the same thing to the due date and touches nothing else — a record due `2026-09-24`,
read on `Pacific/Midway` before 04:00 there, answers `clock=ahead due=2026-09-23`. Until
this was decided the tick waited — **exit 0, no output, no backup, at every tick, until the
calendar reached the date in the file** — and it now takes a backup instead, because the
backup is what repairs the state: the run writes a record dated by this host's own clock, so
the date that stopped the schedule is gone by the end of that run. One extra dump, once, and
it happens whether the dump succeeds or fails. Check this host's clock and `HASHI_BACKUP_TZ`
all the same — one of the two moved — and `make backup` takes one now whatever the record
says.

**What the panel says about it, exactly, because the two halves differ.** The panel goes
loud — a *clock ahead* banner — when the last **success** or the last **failure** in the
record is dated ahead, which is what a clock that jumped forward leaves behind. Those two
fields and no others: a record where only the last *attempt* is ahead is a hand edit, and
it is said on the command line and nowhere else.

**The due date it reads too, and it reads it with a whole day of grace — which splits that
half in two.** The grace is a day because the writer resolves the due date in the
**schedule's** zone while that screen has only its own UTC date, and the inhabited zones
run from UTC−12 to UTC+14; a narrower comparison would put a *clock ahead* banner on a host
scheduled **far enough** east, for **part of every day**, while it backed itself up
perfectly. Measured against the shipped 04:00 schedule, counting the UTC hours at which a
zero-grace comparison would fire: none at all up to UTC+4 — a host there resolving 04:00
local writes a due date equal to the UTC date and would never be flagged — then five hours
out of twenty-four at UTC+9 and ten at UTC+14. A banner that appears daily on a healthy
host is what the grace exists to prevent, and that argument is untouched by the arithmetic
being smaller than "every east host, always". So:

- a due date **more than a day** past that screen's UTC date — a hand-seeded `2099-01-01`,
  a record carried off another machine, a clock that jumped forward by more than a day — is
  loud on the panel as well, since M28.20;
- a due date **no more than a day** ahead is not, and a day is the most `HASHI_BACKUP_TZ`
  moved west can leave — which is the shape an operator actually produces, by editing one
  variable. Measured end to end: a record written under `Pacific/Kiritimati` and read back
  with the schedule moved to `Pacific/Midway` answers `clock=ahead` on the command line and
  gives the panel a quiet, healthy-looking screen — *last backup less than an hour ago*, no
  banner — about a file this host cannot reconcile with its own clock.

(A record whose runs are also old is still loud there, but about their age, which is a
different sentence about a different thing.) For that second shape `make backup-status`
and `scripts/backup-run.sh due` really are the only two channels that say anything, and
both of them name which half they are talking about — so an operator reading one screen and
then the other is not told two different things about one host.

The decision, and the direction it can be reversed in, is in `docs/decisions.md` under
2026-09-24: this is the owner's rule for a record the tick cannot READ carried to one it
cannot TRUST, and it was taken by the orchestrator rather than by the owner.

**A directory at the record's path is refused by name**, on both channels and on the
writing side too. It is what a `mkdir` of the file's own name leaves, and what the docker
daemon creates if a bind mount ever points at the record instead of the directory holding
it. `make backup-status` and `due` call it a record that is there and is not legible —
which is what the panel calls it — rather than a host that has never run one, and a `tick`
refuses before it dumps anything: moving the new record onto a directory does not fail, it
drops `last-run.json.partial` *inside* it, so the schedule used to report success and leave
no record at all, every fifteen minutes. Move the directory aside; nothing here deletes it.

A run that fails is reported by its exit code, unchanged from `make backup`: **1** nothing
was written, **3** the artifact exists and did not leave this machine. Only **1** is retried
automatically, hourly, up to six times a day — a stack that had not finished booting is the
usual cause and a retry costs nothing. **3 is not retried**, because the artifact is already
on the disk and re-dumping would fill it with copies of the same database; the remedy is
the `make backup-upload FROM=…` above, which the failing run prints — and which
`make backup-status` prints too, beside the number, because a bare **3** on a screen says
nothing about the artifact still being on the machine.

A tick with nothing to do prints nothing, so a working schedule is silent and cron sends no
mail. A tick that fails prints everything, and cron delivers that wherever it delivers mail
— which on most hosts is nowhere anybody looks. **The record is the channel that does not
depend on mail existing.**

**On a host with no `crontab`**, the same script under a systemd timer, as root:

```ini
# /etc/systemd/system/hashi-backup.service
[Service]
Type=oneshot
User=<the account that runs `make up`>
ExecStart=<the checkout>/scripts/backup-run.sh tick

# /etc/systemd/system/hashi-backup.timer
[Timer]
OnCalendar=*:0/15
Persistent=true
[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now hashi-backup.timer
systemctl list-timers hashi-backup.timer
```

`OnCalendar=*:0/15` and not `04:00`, for the reason above — the timer carries no hour
either, and `Persistent=true` is then only a belt on top of a schedule that already cannot
skip a day. Everything else is identical: the same script, the same record, the same
`.env`.

**What none of this proves.** That the artifact of any of those runs is still in the
bucket. This host cannot look — see *The retention this host's own key cannot reach*, below
— and a green `make backup-status` is a statement about what happened here, not about what
is kept there. **The panel's line is the same statement in a second place, and no stronger
for being on a screen**: it is read from this host's own record, and nothing in the control
plane has ever read that bucket. The only check is a restore.

### The retention this host's own key cannot reach

The write-only key is the half of the protection that can be taken from you. Whoever holds
this box holds a credential that may `PutObject` **to any name in the bucket, including a
name that is already there** — so "it cannot delete" is not the same as "it cannot
destroy". The rest is enforced by the account that owns the bucket, with a credential that
never comes near this machine.

**The requirement, before any mechanism:** an artifact that was in the bucket yesterday must
still be retrievable tomorrow, by somebody holding a *different* credential, after anything
the key on this host is able to do to that bucket today. Three things get offered as the way
to get there and they are not interchangeable — one is the defence, one is an upgrade to it,
and the third is the thing you are defending against.

| Mechanism | In force? | What it actually defends against |
|---|---|---|
| **Bucket versioning** | **Required. This is the mechanism.** | The overwrite. A `PutObject` to a key that already exists adds a version instead of replacing one, so the one destructive act this host's credential can perform destroys nothing: the earlier bytes stay and are addressable by their version id. It covers the second case too — should the key turn out to have more authority than was intended, a `DeleteObject` under versioning writes a delete marker over versions that are still there. Without it, a single authenticated `PutObject` is a permanent loss and nothing else on this page helps. |
| **Object lock (WORM retention)** | **On top of versioning where the store offers it. Optional, because many S3-compatible stores do not implement it.** | The deletion that versioning does not stop. Versions survive `DeleteObject`; they do not survive `DeleteObjectVersion`, which removes history one version at a time. A locked version cannot be removed until its retention expires — in governance mode, not by anyone without the privilege to bypass it; in compliance mode, not by anyone at all, including the account owner. That second property is also its cost: a period you set too long is paid for in storage until it runs out, and compliance mode cannot be talked out of it. It is defined on versions, so it needs the row above; it is never a substitute for it. |
| **A lifecycle rule** | **Not a retention mechanism. Set one anyway, with a floor you chose on purpose.** | Nothing. It deletes on a schedule — that is its entire function, and under versioning it is the necessary counterweight that stops every version of every daily artifact accumulating for ever. It is therefore also the only thing here that can quietly undo the two rows above. Give noncurrent versions an expiry longer than the longest stretch in which you would not notice that the recent artifacts are garbage, remembering that noticing means *restoring one*, because this host cannot read back what it wrote. A rule that expires noncurrent versions after a few days turns versioning into a few days of protection. |

**So, in one line:** versioning on, object lock on top of it where the store has it, and one
lifecycle rule whose noncurrent expiry you picked deliberately and wrote down.

**The object's name does a different job, and it is not this one.** `make backup` writes
`hashi-<timestamp>.sql.gz.age` and sends it under that name below
`HASHI_BACKUP_S3_PREFIX`, so two runs never collide and a scheduled run cannot clobber the
one before it. That is protection against *accident* and it is worth having. It is not
protection against anybody: the uploading key chooses the name, so it can name an object
yesterday's name, and a bucket without versioning will accept that `PutObject` and keep the
last one written. **The naming means nobody loses a backup by mistake; versioning is what
means nobody loses one on purpose.**

**If the store offers none of it.** First, ask properly rather than concluding it from a
console page that had no checkbox on it — the three calls below answer it definitively, and
versioning is the one of the three a store is likeliest to have. If the answer is genuinely no, the
protection moves off the bucket and onto **a copy you pull down**: a machine that is not the
control plane, holding the read credential from *What you carry*, fetches new objects out of
the bucket on whatever cadence you can actually keep, onto media you hold. The artifact is
already `age` ciphertext, so a copy on your own disk is no more exposed than the copy in the
bucket; what it buys is that it is out of reach of this host's key entirely, which is the
property versioning would have given you. **The cadence of the pull is the size of the
window you can lose.**

What is *not* a fallback: a second destination configured in `.env` here. Two buckets
written by two keys on the same box are two things one seizure takes. Nor is giving this
host a key that can delete so it can tidy up after itself — tidying is the lifecycle rule's
job, and it is row three above. Moving the whole thing to a store that does offer versioning
costs four lines of `.env` and no code, which is what keeping the store a *field* bought;
whether to move is the owner's call and the constraints on it are recorded in
`docs/decisions.md`, not re-argued here.

**Checking it is really in force — from anywhere that is not this host.** You cannot check
with the credential in `.env`, by construction: it can write and it can do nothing else.
With an administrative credential for the bucket, on your own machine, ask the store
directly:

- `GetBucketVersioning` — the answer must be `Enabled`. `Suspended`, and an empty answer,
  both mean new writes are unversioned; the difference between the two is only whether
  versions were ever kept at all.
- `GetObjectLockConfiguration` — the mode and the period, or an error saying the store does
  not implement it. An error is not a failed check here; it is the answer to whether row two
  is available to you.
- `GetBucketLifecycleConfiguration` — read the noncurrent-version expiry and compare it to
  the number you chose. This is the one that drifts, because it is the one somebody edits
  later to save money.

Those are the protocol's own names for the three settings, not one store's menu: what a
console calls them differs from store to store, and a store that does not implement one
answers the call with an error rather than under a different name. That is why they are
written here as calls and not as a path through somebody's console.

A setting can read `Enabled` and still not be doing what you assume, so confirm it
empirically as well: with that same administrative credential, `PutObject` a throwaway
object twice under one key, then `ListObjectVersions` under its prefix. **Two versions is
versioning working. One is the state this entire section exists to prevent.** Objects that
were already in the bucket are protected from the moment versioning is switched on, but
nothing brings back a write that happened while it was off — so the check belongs at bucket
creation, after any credential rotation, after a move to another store, and after anybody
touches a lifecycle rule. Not once a year.

**What this repository cannot tell you, and never will.** No test in this tree asserts any
of the above. It cannot: the only credential this project holds is write-only by design,
there is no read, list or delete path anywhere in the product, and the bucket lives in an
account this code has no standing in. `make verify` proves the artifact is written, that it
is encrypted before it reaches the disk, and that a store accepted exactly those bytes — it
says nothing whatever about what that store does with them a minute later. The calls above
are the only proof there is, you are the only one who can run them, and the day you will
wish they had been true is a day you can no longer run them.

### What belongs in a backup, and what does not

Decided 2026-09-23, item by item, because "everything the control plane generates" is not
self-evident at 3am and half of it is key material.

| Item | Backed up? | Why |
|---|---|---|
| **The control database** (the `hashi-db` volume, via `make backup`) | **Yes** — it *is* the backup | The single source of truth. Every node, every transport row, every user and every credential. Nothing else in this table can be reconstructed *from* the others; this can reconstruct a whole fleet. |
| **`caddy_data`** (Caddy's ACME account key, its issued certificates, and the internal CA root the panel is served with) | **No** | Every byte of it regenerates on first boot with no operator action, and after a seizure the old host's private keys are to be presumed compromised — restoring them carries the seized machine's identity onto the new one. The cost of regenerating is real but bounded, and it is spelled out below rather than assumed. |
| **`~/.hashi/management/`** (this host's management-tunnel private key, its per-host obfuscation values, and every enrolled device's public key and pre-shared key) | **Yes** — but only inside the age-encrypted artifact, never in the plain dump above | It is regenerable but **not reproducibly**: `scripts/management-tunnel.sh` prints each device's config exactly once and keeps no copy, so a fresh run invalidates every device already enrolled. Losing it means re-enrolling your laptop *and* your phone by copying a freshly printed private key out of an SSH session, at the moment the panel is unreachable and you are rebuilding under pressure — which is the one moment the tunnel exists for. It is 32 bytes and it is the difference between typing one new `Endpoint` line per device and re-doing the whole enrolment. |
| **`.env`** | **NO. Not in the artifact, not in the bucket, not even encrypted.** | It holds `HASHI_SECRET_KEY`, which is the *only* thing standing between a reader of the bucket and every node credential and user token in the dump. Putting it beside the data defeats the encryption entirely: one stolen age identity would then yield both halves. Excluding it is what makes a restore cost **two** secrets that never meet on this host — the age identity and `HASHI_SECRET_KEY`, both carried by you. It also holds `HASHI_OPERATOR_PASSWORD_HASH`, so it is what lets you log in at all; see *What you carry*, below. Rebuild it on the new machine from `.env.example` plus what you carry. |
| **`deploy/delivery/`** (the delivery wildcard and its private key, when you use one) | **No** — `make backup` does not read that directory | The same reasoning as `caddy_data`: a seized host's key is presumed compromised, and the wildcard is re-issuable. After a restore no host serves refreshes of its own until you put a pair back (*The delivery certificate*), and the Nodes screen says so. |
| **`/opt/hashi` on a node** | **No**, explicitly | A node holds nothing that cannot be regenerated from the database — that is the invariant that makes replacing a node safe. Its rendered configs come back from an apply. Backing a node up would be backing up a derived artifact and calling it a source. |

### What a restore of the database actually gives you back

Every node record, every transport row, every user and every subscription token — so
**every user's existing subscription URL keeps working**, with no message to anyone,
*provided the delivery name still resolves to the new host*. If the domain itself is
gone, that is the one thing no backup returns: the tokens survive and the URL they live
in does not, and every user has to be handed a new link.

It does not give you back:

- **Anything readable without `HASHI_SECRET_KEY`.** Under the wrong key the panel loads
  and every screen that touches a node or a user answers *"The data is intact; the key is
  wrong. Nothing has been changed."*
- **A way to log in.** `HASHI_OPERATOR_PASSWORD_HASH` lives in `.env`, not in the
  database. `make hash-password` makes a new one on the host itself.
- **A backup.** `HASHI_BACKUP_AGE_RECIPIENT` and the write-only S3 credential were in
  `.env` too, and the schedule was a crontab on the machine that is gone — so the host
  that came out of the backup history cannot add to it until you put both back and run
  `make backup-schedule`. Nothing fails loudly on its own: `make backup` refuses, and the
  panel truthfully reports that nothing has been recorded here.
- **A working fleet.** Restoring records does not touch a node. The new control plane
  believes in nodes that may be seized, blocked or gone; you re-apply to the ones you
  still hold and delete the ones you do not.
- **The management tunnel**, unless you carried `~/.hashi/management/` (above).
- **The delivery certificate.** `.env` names it and `deploy/delivery/` held it, and
  neither is in the artifact. Until a pair is back there, each apply stands down the
  listener of every host it reaches and takes the old key off it; a host no apply reaches
  keeps serving what it held.

### The `caddy_data` cost, stated rather than waved at

On a new host Caddy registers a fresh ACME account and requests a fresh certificate for
`HASHI_PUBLIC_HOST` the first time a publishing command (`make up-panel`,
`make up-panel-over-ssh`) brings it up — not when the restore boots it, because that
stack publishes nothing and asks no CA (M31.1). Issuance needs the name to already
resolve to the new machine and inbound `:80`/`:443` to reach it; until both are true,
`/sub/*` serves nothing, so move the record before you publish. Users with a working config are unaffected — a user who needs to
*refresh* one is not.

Issuance is rate-limited at the CA, and the binding limit for a rebuild is the
**duplicate-certificate** one: for an identical set of names it is five per week, on top
of a per-registered-domain limit an order of magnitude higher. One rebuild spends one.
You would have to rebuild the same name six times in seven days to be refused, and the
refusal degrades the delivery endpoint only.

The panel is not affected either way: it is served with `tls internal`, Caddy's own CA,
created at first boot and never published to a CA's logs. What you do lose is that the
root is **new**, so each device is asked to trust the console once more. On a deliberate
rebuild that prompt is expected. A prompt you did *not* expect is the one to refuse.

Both paragraphs above are read from the issuer's published limits and from this
repository's own Caddyfile. Neither is measured — see *Known-unproven*.

### What you carry

Three things live on you and never on the control host. The first two are needed by every
restore of an artifact written since 2026-09-23 — the file does not even open without the
second. The third is needed from the moment anything is in the bucket, which since
2026-09-23 it is.

1. `HASHI_SECRET_KEY` — without it the dump is unreadable data.
2. The **private half** of the age keypair whose public half is `HASHI_BACKUP_AGE_RECIPIENT`.
   Without it the artifact does not open at all, on any machine, including this one.
3. A **read** credential for the backup bucket — `ListBucket` and `GetObject` — and, to
   check the retention above, an administrative one. The key in `.env` can only write, on
   purpose, so the box that is seized cannot delete its own history; the direct consequence
   is that fetching an artifact back out of the bucket, and asking that bucket whether
   versioning is on, are both things only you can do. `make restore-from-bucket` does the
   fetching *with the credential you hand it*, in its own environment, for the length of
   one command — neither it nor the age identity is ever written into `.env` on this host,
   and the command refuses rather than reading them from there.

Plus the values needed to rewrite `.env` itself — hosts, ports, the Postgres password,
and a password for the panel. The operator password **hash** is not on that list any more:
`make hash-password` makes it on the host, so what you carry is the password itself, in
your head. Everything else in that file comes from `.env.example`.
