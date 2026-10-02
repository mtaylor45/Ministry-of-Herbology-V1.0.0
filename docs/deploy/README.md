# Deploying The Ministry of Herbology

This is a self-hosted application. Nobody operates it for you, there is no
staging environment belonging to this project, and there is no account to sign
up for. You run it on your own machine, from your own registry, behind your own
certificate. Everything you need is in this repository.

This guide assumes you have never seen this codebase. It does not assume you
know Docker swarm well. Follow it top to bottom once and you will have a
working installation; after that, **Upgrading** and **Backup and restore** are
the two sections you will come back to.

Nothing here asks you for a credential and nothing here gives you one. Every
password, token and key in this document is one you generate, with the command
shown. If you find a working value anywhere in this repository, that is a bug
worth reporting.

---

## Contents

1. [What you are about to run](#1-what-you-are-about-to-run)
2. [Prerequisites](#2-prerequisites)
3. [Build and push your images](#3-build-and-push-your-images)
4. [Initialise a swarm](#4-initialise-a-swarm)
5. [Certificates](#5-certificates)
6. [Create the secrets](#6-create-the-secrets)
7. [Write your .env.deploy](#7-write-your-envdeploy)
8. [Deploy](#8-deploy)
9. [First run: the schema](#9-first-run-the-schema)
10. [Fixtures, and why you probably do not want them](#10-fixtures-and-why-you-probably-do-not-want-them)
11. [Connecting Home Assistant](#11-connecting-home-assistant) — and [calendar push](#calendar-push-to-a-caldav-calendar)
12. [Upgrading](#12-upgrading)
13. [Backup and restore](#13-backup-and-restore)
14. [Two standing rules](#14-two-standing-rules)
15. [Troubleshooting](#15-troubleshooting)
16. [What has and has not been executed](#16-what-has-and-has-not-been-executed)

---

## 1. What you are about to run

Nine services on one Docker swarm:

| Service | Image | What it is |
| --- | --- | --- |
| `db` | `timescale/timescaledb:2.17.2-pg16` | Postgres 16 with TimescaleDB. All the data. |
| `redis` | `redis:7-alpine` | The Arq job queue. |
| `mosquitto` | `eclipse-mosquitto:2.0.20` | MQTT broker, for Home Assistant. |
| `api` | `moh-api` (yours) | The FastAPI application. |
| `web` | `moh-web` (yours) | The SvelteKit PWA. |
| `worker-weather` | `moh-worker` (yours) | Forecast ingest, water balance, frost guard. |
| `worker-botany` | `moh-worker` (yours) | Taxon resolution and cited care synthesis. |
| `worker-hub` | `moh-worker` (yours) | The Home Assistant adapter and MQTT publisher. |
| `worker-plates` | `moh-worker` (yours) | Botanical plate sourcing for the Journal. |
| `nginx` | `nginx:1.27-alpine` | TLS, and one origin for the app and the API. |

Three images are yours to build. The rest come from Docker Hub.

Two overlay networks. `data` is `internal: true` — the database, Redis and the
broker sit only on it, so they cannot reach the internet and nothing outside
the stack can reach them. `app` carries the front door and gives the API and
the workers the outbound access they need for Open-Meteo, POWO and your Home
Assistant.

Two ports are published on the node: 443 (and 80, which only redirects) for the
app, and 1883 for MQTT. **Put 1883 on your LAN and not on the internet.**

Seven named volumes. Four hold the data services' own state. The other three
hold **pictures, not rows**, and `pg_dump` knows nothing about them:
`grounds-images` (uploaded plans and surveys for the map), `plates-images`
(the Journal's botanical plates) and `photos-images` (the household's
photographs). The API serves all three; the plates worker writes plates. They
are part of the backup — [§13](#13-backup-and-restore) — because a restore
that brings back the database and not the volumes is a map whose layers all
answer 404, a book with no plates and a growth log with no photographs, which
is exactly what the contract says that looks like.

---

## 2. Prerequisites

* **A Linux machine** with Docker Engine 24 or newer. One is enough; the stack
  is written for more but assumes nothing about them.
* **A container registry you can push to.** Any of these is fine:
  * a private registry — Harbor, Nexus, a plain `registry:2` on the same box;
  * `ghcr.io/<you>` or Docker Hub;
  * nothing at all, if you build on the same single node you deploy to — see
    the note at the end of [§3](#3-build-and-push-your-images).
* **A TLS certificate** for the hostname you will use. [§5](#5-certificates).
* **A hostname** that resolves to the machine, at least from wherever you will
  use the app.
* **`git`, `make` and `openssl`** on the machine you build from.

Check Docker first, because everything below depends on it:

```sh
docker version
docker info | grep -i 'server version'
```

Then get the code:

```sh
git clone https://github.com/mtaylor45/Ministry-of-Herbology-V1.0.0.git
cd Ministry-of-Herbology-V1.0.0
```

Keep this checkout. The stack file, the Nginx config and the migration,
backup and restore scripts all live in it, and you will need it again at every
upgrade.

---

## 3. Build and push your images

Set your registry — your host and your namespace, no trailing slash:

```sh
export MOH_REGISTRY=registry.example.net/ministry-of-herbology
```

Log in to it, however your registry expects:

```sh
docker login registry.example.net
```

Then:

```sh
make push MOH_REGISTRY="$MOH_REGISTRY"
```

That builds `moh-api`, `moh-web` and `moh-worker` and pushes all three. The tag
comes from `git describe --tags --always --dirty`, so it identifies the commit
the image was built from. If your working tree is dirty the build refuses,
because a tag that does not identify its source is worse than no tag:

```
The working tree has uncommitted changes, so 0e811f9-dirty would not
identify what is in the image.
```

Commit, or accept it with `MOH_ALLOW_DIRTY=1`.

The last line tells you the tag to deploy. Write it down:

```
Deploy this build with:  MOH_IMAGE_TAG=v0.3.0 make stack-deploy
```

To build without pushing — to check the Dockerfiles work before you have a
registry — use `make images`.

> **One machine, no registry.** If you build on the same single node you deploy
> to, the images are already in that node's local store and swarm will find
> them. Set `MOH_REGISTRY` to any prefix you like (`local/moh` will do), run
> `make images` instead of `make push`, and deploy in §8 with
> `make stack-deploy MOH_RESOLVE_IMAGE=never` — with no registry to ask for
> each image's digest, the default `always` fails. `make images` prints the
> tag it built in place of the line above. This does not work with more than
> one node: the other nodes have no copy.

---

## 4. Initialise a swarm

If `docker info` says `Swarm: inactive`:

```sh
docker swarm init --advertise-addr <this machine's LAN IP>
```

Use the address other machines can reach, not `127.0.0.1`, unless this really
is a single node that nothing else will ever join.

That single node is now a manager, which is all the stack needs. To add more
later, `docker swarm join-token worker` prints the command to run on them.

The database, the broker, the API and the plates worker are pinned to
`node.role == manager`, because each owns or shares a local volume and a
volume does not follow a task to another node. The API and the plates worker
in particular share `plates-images` — one writes, the other serves — so they
have to be on the same machine. On one node none of this is visible; on
several it is what keeps the pictures beside the rows that point at them.

---

## 5. Certificates

**This repository does not generate, bundle or suggest a certificate.** You
supply one. Two normal ways:

**Let's Encrypt, DNS-01.** Works whether or not port 80 is reachable from the
internet, and it is what you want for a hostname that only resolves on your
LAN. Use `certbot` or `lego` with your DNS provider's plugin. You end up with
`fullchain.pem` and `privkey.pem`.

**Let's Encrypt, HTTP-01.** Needs port 80 reachable from the internet. The
Nginx config serves `/.well-known/acme-challenge/` from a volume for exactly
this, so a webroot challenge works: point your client's webroot at the
`moh_acme` volume.

**Your own CA, or a self-signed certificate.** Fine for a LAN-only
installation, as long as you understand that every browser will object until
you install the CA on it.

Whatever you use, you need two PEM files:

* the **full chain** — your certificate followed by any intermediates, in that
  order. A certificate without its intermediates works in a browser you have
  already visited and fails on a phone, which is a miserable way to find out.
* the **private key**, unencrypted. Nginx has nowhere to ask you for a
  passphrase.

Check before you go further:

```sh
openssl x509 -in fullchain.pem -noout -subject -dates
openssl x509 -in fullchain.pem -noout -modulus | openssl sha256
openssl rsa  -in privkey.pem   -noout -modulus | openssl sha256   # must match
```

(For an ECDSA key, `openssl ec` instead of `openssl rsa`.)

### Renewal

Swarm secrets are immutable, so renewal is: create new secret objects, point
the service at them, remove the old ones. See
[Renewing the certificate](#renewing-the-certificate) under Upgrading.

---

## 6. Create the secrets

Six secrets. None of them has a default, and none of the commands below
contains a value — each one either generates something or reads a file you
made.

Run these on a swarm **manager**.

### `moh_db_password` — the Postgres password

Generate it. Do not choose it, and do not reuse one:

```sh
openssl rand -base64 39 | tr -d '\n' | docker secret create moh_db_password -
```

`tr -d '\n'` matters: a trailing newline inside the secret is a character in
the password on one side of the connection and not the other, and you will
spend an hour on it. (The entrypoint strips trailing newlines for exactly this
reason, but the database's own copy comes from here.)

You never need to see this value again. If you want it later:
`docker exec $(docker ps -qf name=moh_db) cat /run/secrets/moh_db_password`.

### `moh_mqtt_password` — what the app logs in to the broker with

```sh
openssl rand -base64 30 | tr -d '\n' | docker secret create moh_mqtt_password -
```

### `moh_mqtt_passwords` — the broker's own password file

Mosquitto wants a hashed password file, not a password. Make one with
Mosquitto's own tool, using **the same password you just generated**:

A secret cannot be read back once created, so the two halves have to come
from one value. Generate it once, into a shell variable, and create both
secrets from it — this replaces the `moh_mqtt_password` line above, so if you
already ran that one, `docker secret rm moh_mqtt_password` first:

```sh
# In one shell session. The variable never reaches a file.
MQTT_USER=herbology
MQTT_PASSWORD=$(openssl rand -base64 30 | tr -d '\n')

printf '%s' "$MQTT_PASSWORD" | docker secret create moh_mqtt_password -

docker run --rm -i eclipse-mosquitto:2.0.20 \
  sh -c "mosquitto_passwd -c -b /tmp/pw '$MQTT_USER' '$MQTT_PASSWORD' >/dev/null && cat /tmp/pw" \
  | docker secret create moh_mqtt_passwords -

unset MQTT_PASSWORD
```

Then set `MOH_MQTT_USERNAME=herbology` in `.env.deploy` (or whatever you used
for `MQTT_USER`).

> The password appears in that `docker run` command line, and therefore in the
> shell history of this one session and in `ps` output for the second or so it
> runs. On a machine only you can log into that is acceptable; if it is not,
> run `mosquitto_passwd` interactively instead (`-c` without `-b`, and it will
> prompt) and pipe the resulting file in.
>
> Clear the history line afterwards if you care: `history -d $((HISTCMD-1))`.

### `moh_ha_token` — a Home Assistant long-lived access token

If you have Home Assistant, see [§11](#11-connecting-home-assistant) for where
the token comes from, then:

```sh
docker secret create moh_ha_token /path/to/the/token/file
```

**If you do not have Home Assistant**, the secret still has to exist — swarm
refuses to start a service that refers to a secret that is not there. Create it
blank:

```sh
printf '\n' | docker secret create moh_ha_token -
```

(`docker secret create` rejects genuinely empty input, hence the newline; the
entrypoint strips it, so the application sees an empty token and reports the
integration as not configured, which is exactly right.)

### `moh_tls_cert` and `moh_tls_key`

From the files in [§5](#5-certificates):

```sh
docker secret create moh_tls_cert /path/to/fullchain.pem
docker secret create moh_tls_key  /path/to/privkey.pem
```

### Check

```sh
docker secret ls --format '{{.Name}}'
```

All six must be listed:

```
moh_db_password
moh_ha_token
moh_mqtt_password
moh_mqtt_passwords
moh_tls_cert
moh_tls_key
```

---

## 7. Write your `.env.deploy`

`docker stack deploy` interpolates variables from the shell and has no
`--env-file`, so `make stack-deploy` sources this file for you. It is in
`.gitignore`; keep it there.

`.env.example` documents every variable. The minimum:

```sh
cat > .env.deploy <<'EOF'
MOH_REGISTRY=registry.example.net/ministry-of-herbology
MOH_IMAGE_TAG=v0.3.0
MOH_PUBLIC_BASE_URL=https://herbology.example.net
MOH_NWS_USER_AGENT=ministry-of-herbology (you@example.net)
EOF
```

Replace all four. They are the four the deploy refuses to proceed without, and
it names each one:

```
required variable MOH_PUBLIC_BASE_URL is missing a value:
set MOH_PUBLIC_BASE_URL, e.g. https://herbology.example.net
```

`MOH_PUBLIC_BASE_URL` is the URL you will actually type into a browser, with no
trailing slash. It goes into the calendar feed URLs and the PWA manifest, so a
wrong value shows up days later rather than immediately.

`MOH_NWS_USER_AGENT` wants a real contact address. The US National Weather
Service refuses traffic without one and is entitled to.

Everything else has a default. Render the whole thing to see what you are
about to get:

```sh
make stack-config | less
```

---

## 8. Deploy

```sh
make stack-deploy
```

It returns when every service is running as many tasks as it should, steadily,
which takes a minute or two the first time — the database's `start_period` is
90 seconds, because first-time initialisation takes a while and a healthcheck
that fires too early reports a half-built database as healthy.

If something never comes up, it gives up after ten minutes (set
`MOH_DEPLOY_TIMEOUT`, in seconds, to change that) and prints each service that
is short of tasks, its last errors and the end of its log. A service that
starts and dies in a loop is the usual cause, and its log says why. The same
report at any time: `scripts/stack_why.sh`. To look yourself:

```sh
make stack-ps
```

When it is quiet:

```sh
curl -s  http://localhost/healthz             # nginx itself, on port 80
curl -sk https://localhost/api/v1/healthz     # the API through nginx
```

The app will not be much use yet: the database has no schema.

---

## 9. First run: the schema

`contracts/schema/` holds numbered, forward-only migrations. The dev compose
mounts them into `docker-entrypoint-initdb.d`, which the Postgres image runs
**only when the data directory is empty** — fine for creating a database,
useless for upgrading one. The deployed stack does not use it at all.

Instead, from your checkout, on the node running the database:

```sh
scripts/migrate.sh status
```

```
MIGRATION                          STATE     APPLIED AT
001_init.sql                       pending   -
002_rollups.sql                    pending   -
003_weather_obs_unique.sql         pending   -

3 migration(s) pending. Run: scripts/migrate.sh apply
```

Then:

```sh
scripts/migrate.sh apply     # or: make migrate
```

Each file is applied together with its ledger row in one transaction, so a
migration either lands completely and is recorded or does neither. Re-running
`apply` is safe and does nothing.

The ledger lives in `moh_deploy.schema_migration` — its own schema, so it is
unmistakably deployment bookkeeping rather than part of the frozen contract:

```sh
scripts/migrate.sh status
```

The script reaches the database by `docker exec` into the Postgres task, which
means it never handles the database password and needs no published port. It
has to run on the node where that task is: if it cannot find it, it says so and
tells you to check `docker service ps moh_db`.

**Adopting an existing database.** If you have a database this application
built some other way — the dev compose, or a restored dump from before this
ledger existed — `scripts/migrate.sh baseline` records the files as applied
without running them. It executes nothing. Only do it when you are sure the
schema already matches.

---

## 10. Fixtures, and why you probably do not want them

`fixtures/` holds the sample data every parts of the project develops against: a
household, some plants, recorded weather. `scripts/load_fixtures.py` loads it.

**Do not load fixtures into an installation you intend to use.** They are not a
starter kit. They are a specific fictional household whose plants and history
exist to make tests deterministic, and separating them from your own plants
afterwards is tedious and error-prone.

Load them if you are evaluating the app and will throw the database away, or if
you are reproducing a bug. Otherwise skip this section entirely and add your
first plant through the UI.

To load them into a deployed stack — after [§9](#9-first-run-the-schema), on
the node running the database:

```sh
python3 scripts/load_fixtures.py --sql \
  | docker exec -i $(docker ps -qf name=moh_db) psql -q -v ON_ERROR_STOP=1 -U herbology -d herbology
```

The script prints the load as one SQL transaction and `psql` inside the
database container runs it, the way `scripts/migrate.sh` reaches the database:
nothing is published and no password is handled. It **empties the household's
tables first**, which is the other reason not to point it at a database you
care about. It needs only `python3`, with nothing installed.

---

## 11. Connecting Home Assistant

Optional. The app runs perfectly well without it and says "not configured"
rather than pretending otherwise. Under the design, Home Assistant is the only
route for sensor readings, so without it you have weather and your own
observations and no soil moisture.

**Get a token.** In Home Assistant: your profile → Security → Long-lived access
tokens → Create token. You see it exactly once. Put it in a file:

```sh
printf '%s' 'the-token-you-just-copied' > /tmp/ha-token
docker secret rm moh_ha_token                    # the blank one from §6
docker secret create moh_ha_token /tmp/ha-token
shred -u /tmp/ha-token
```

Removing a secret that a running service uses fails; if it does, see
[Rotating a secret](#rotating-a-secret) — the procedure is the same.

**Point the app at it** in `.env.deploy`:

```
MOH_HA_BASE_URL=http://homeassistant.local:8123
```

**Optionally, choose a notify service.** Watering reminders and frost
warnings go to each household member's own Home Assistant notify service,
chosen in their profile. For a member who has not chosen one — the one phone
in a one-phone household — the hub worker falls back to a deployment-wide
service, if you name it:

```
MOH_HA_NOTIFY_SERVICE=notify.mobile_app_your_phone
```

Its name is in Home Assistant under Developer tools → Actions, and it is a
service name, not a credential. Leave it unset and nobody is notified, which
the Ministry Office reports as a setup step rather than as a fault. The app
will never guess `notify.notify` for you: that is every device in the house.

**Point Home Assistant at the broker.** In Home Assistant: Settings → Devices
and services → Add integration → MQTT.

* Broker: the LAN address of this machine
* Port: `1883` (or your `MOH_MQTT_PORT`)
* Username: your `MOH_MQTT_USERNAME`
* Password: the one you generated for `moh_mqtt_password`

Then redeploy so the services pick up the changes:

```sh
make stack-deploy
```

The Ministry Office screen will show the integration as configured, and then as
healthy once a reading arrives.

### Calendar push to a CalDAV calendar

Optional, and separate from Home Assistant. Every member can already
*subscribe* to their tending calendar: the Ministry Office hands out an ICS
address, and that needs nothing from you. Push is for a calendar that should
change within minutes of a task changing — the subscribed kind refreshes when
the calendar app decides to. It works with any CalDAV server: iCloud,
Fastmail, Nextcloud, Radicale.

**Google Calendar push is not available in this version.** It would need an
OAuth client registered with Google and a store for every member's refresh
token, which this app deliberately does not have. A member on
Google subscribes to the ICS address instead; Google refreshes subscribed
calendars slowly, often twelve hours or more, and the Office says so.

The credential is never typed into the app and never stored by it. It is a
swarm secret you create, one per feed, which the API reads at the moment it
pushes and keeps nothing of — no database column, no log line, no error
message carries any part of it.

**1. Create the feed.** In the Ministry Office, create a calendar feed with
push to CalDAV. Its push status reads *awaiting the operator* and the Office
shows the feed's id, which is not a secret, and the secret's name:
`moh_caldav_<feed_id>`.

**2. Make an app password** at your calendar provider, for this app alone, so
revoking it touches nothing else you use. Use an app password rather than
your account's own wherever the provider offers one; iCloud and Fastmail
require it.

**3. Create the secret.** Three lines, in this order:

1. the calendar collection's `https://` URL — the calendar itself, not the
   account's address;
2. the username;
3. the app password.

Write them with `read`, so none of the three reaches your shell history or a
file. The feed id below is the one the Office showed you:

```sh
FEED=paste-the-feed-id-here
read -r URL; read -r USER_NAME; stty -echo; read -r APP_PASSWORD; stty echo
printf '%s\n%s\n%s\n' "$URL" "$USER_NAME" "$APP_PASSWORD" \
  | docker secret create "moh_caldav_$FEED" -
unset URL USER_NAME APP_PASSWORD
```

**4. Hand it to the API.** This is the step that is easy to miss. In a swarm a
secret reaches a service only if the service lists it, and creating it lists
it nowhere. The API is the service that pushes:

```sh
docker service update --secret-add "moh_caldav_$FEED" moh_api
```

(`moh` is your stack's name, `MOH_STACK`.) The API's tasks are replaced one at
a time and the secret appears in each at `/run/secrets/moh_caldav_<feed_id>`.
Within a minute the push status turns to *ok*, or to *failing* with a
sentence saying what the server answered.

A later `make stack-deploy` carries every `moh_caldav_*` secret in the swarm
across to the API on its own: `docker stack deploy` resets a service to what
the stack file lists, which would otherwise quietly drop the ones added here.
If you deploy with `docker stack deploy` by hand instead, repeat step 4 for
each feed afterwards.

**iCloud: use your account's own server address.** iCloud's calendars live on
a numbered host, `pNN-caldav.icloud.com`, where `NN` is particular to your
account. A collection URL on `caldav.icloud.com` is answered with a redirect
to that host, and the app does **not** follow a redirect while signed in: a
redirect is a request to send your app password somewhere you did not write
down, so the push stops and the status says *failing*, naming the redirect.
Put the final `pNN-caldav.icloud.com` address in the secret's first line. If
you are unsure of it, the CalDAV account settings of an app already syncing
that iCloud calendar show the server it ended up on.

**Changing or revoking.** A secret cannot be edited, and the name is the
feed's, so changing the credential is: take it off the API, remove it, create
it again, hand it back.

```sh
docker service update --secret-rm "moh_caldav_$FEED" moh_api
docker secret rm "moh_caldav_$FEED"
# step 3 again, then step 4 again
```

In between, that one feed reads *awaiting the operator* and pushes nothing;
the next push after step 4 catches it up, because pushing is by event and
sequence and repeats nothing. Revoking the feed in the Office stops its push at
once; the first two lines above then remove the credential for good. No other
feed is touched by either.

---

## 12. Upgrading

### To a new image tag

```sh
git pull
make push                                  # builds and pushes the new tag
$EDITOR .env.deploy                        # set MOH_IMAGE_TAG to what it printed
scripts/migrate.sh status                  # any new migrations?
make stack-deploy
```

The API and the web app roll one task at a time, `start-first`, and roll back
on their own if the new task never turns healthy. Watch it:

```sh
make stack-ps
docker service logs -f moh_api
```

**Migrations and the order to run them in.** Apply migrations *before*
deploying if the new schema is backwards-compatible with the running code
(adding a table, adding a nullable column — nearly all of them). Apply them
*after* only if a migration would break the old code, and accept that the app
is down in between. The project's migrations are forward-only and additive by
policy, so before is the normal answer.

Always take a backup first. It takes seconds:

```sh
make backup
```

### The `moh_uploads` volume, on a stack deployed 

Earlier stack files declared an `uploads` volume to hold the place for
photographs before the upload existed. Nothing ever wrote to it; photographs
now live on `moh_photos-images`. After the first deploy of this version it is
no longer mounted by anything, and once you have checked it is empty you can
remove it:

```sh
docker run --rm -v moh_uploads:/data:ro alpine:3 find /data -mindepth 1 | head
docker volume rm moh_uploads
```

### Rolling back

```sh
docker service rollback moh_api
docker service rollback moh_web
```

Or set `MOH_IMAGE_TAG` back to the previous tag and `make stack-deploy` again.
This is why you pin a tag rather than using `latest`: a rollback you cannot
name is not a rollback.

**A migration does not roll back.** `contracts/schema/` is forward-only by
design. If a deployment has to be undone *and* it applied a migration, the
route back is a restore from the backup you took. Which you did take.

### After editing a config file

`infra/stack/nginx/*.conf` and `infra/stack/mosquitto/mosquitto.conf` become
swarm config objects, and **swarm config objects are immutable**. Editing the
file changes nothing on its own — the old content keeps being served and
nothing tells you. Increment the version:

```
MOH_CONFIG_VERSION=2
```

in `.env.deploy`, then `make stack-deploy`. The old objects can be removed with
`docker config rm` once nothing references them.

### Rotating a secret

A swarm secret cannot be edited, and swarm will not remove one a running
service uses, so a rotation is: create the replacement under a new name, tell
the stack that name, deploy. Every secret in the stack file has a variable for
this — `MOH_DB_PASSWORD_SECRET`, `MOH_MQTT_PASSWORD_SECRET`,
`MOH_MQTT_PASSWORDS_SECRET`, `MOH_HA_TOKEN_SECRET`, `MOH_TLS_CERT_SECRET`,
`MOH_TLS_KEY_SECRET` — each defaulting to the secret's original name. The path
inside the containers never changes, so nothing else needs to know.

The database password, which has two halves — the secret, and the database's
own copy:

```sh
# 1. The replacement, under a new name. In one shell session; the variable
#    never reaches a file.
NEW=moh_db_password_$(date +%Y%m%d)
DB_PASSWORD=$(openssl rand -base64 39 | tr -d '\n')
printf '%s' "$DB_PASSWORD" | docker secret create "$NEW" -

# 2. The database's own copy, through psql's standard input rather than its
#    command line, so it is in no process listing.
printf "ALTER ROLE herbology PASSWORD '%s';\n" "$DB_PASSWORD" \
  | docker exec -i $(docker ps -qf name=moh_db) psql -q -U herbology -d herbology
unset DB_PASSWORD

# 3. Name it in .env.deploy, and deploy.
echo "MOH_DB_PASSWORD_SECRET=$NEW" >> .env.deploy
make stack-deploy

# 4. Only now: the old one. Its name is whatever the variable said before
#    step 3 — moh_db_password, the first time.
docker secret rm moh_db_password
```

Between steps 2 and 3 the running services still hold the old password, and
their open connections keep working; a new connection fails until the deploy
replaces them, which takes a minute. Do it when nobody is ticking off tasks.

Every later `make stack-deploy` reads the same line and keeps the new name.
If `.env.deploy` names a secret twice, the last line wins. `make preflight`
checks the names the file gives, so a typo is reported before anything is
touched.

The others are the same three steps without the database half. The MQTT pair
has two halves too: the broker's file and the app's password must come from
one value, as in [§6](#moh_mqtt_passwords--the-brokers-own-password-file),
so rotate `moh_mqtt_password` and `moh_mqtt_passwords` together, under two new
names, in one deploy.

### Renewing the certificate

The same rotation, and the one you will do most often:

```sh
STAMP=$(date +%Y%m%d)
docker secret create "moh_tls_cert_$STAMP" /path/to/fullchain.pem
docker secret create "moh_tls_key_$STAMP"  /path/to/privkey.pem

echo "MOH_TLS_CERT_SECRET=moh_tls_cert_$STAMP" >> .env.deploy
echo "MOH_TLS_KEY_SECRET=moh_tls_key_$STAMP"   >> .env.deploy
make stack-deploy
```

Then remove the previous pair by name (`docker secret ls` lists them).

Nginx is `mode: global` with host ports, so this restarts the front door: a few
seconds of downtime, once every ninety days. Automate it alongside your ACME
client's renewal hook. Because the names live in `.env.deploy`, a later deploy
keeps them; this was a `docker service update`, which the next
`make stack-deploy` quietly undid.

---

## 13. Backup and restore

What to back up is two things: **the database**, and **the three volumes that
hold pictures** — `moh_grounds-images`, `moh_plates-images` and
`moh_photos-images`.
The rows in the database point at files in the volumes; either half without
the other is not a recovery. One command takes both.

### Taking a backup

```sh
make backup
```

or, to choose where it goes:

```sh
scripts/backup.sh --out /srv/backups
scripts/backup_volumes.sh --out /srv/backups
```

The first writes `moh-<database>-<timestamp>.dump` — `pg_dump
--format=custom`, which compresses and lets `pg_restore` reorder objects on
the way back in. That reordering matters with TimescaleDB: hypertables have
to exist before their data arrives.

The second writes one `moh_<volume>-<timestamp>.tar.gz` per picture volume,
through a throwaway `alpine` container that mounts the volume read-only.
Nothing in the stack is stopped for it.

Every file is written to a `.partial` name and renamed when complete, so an
interrupted backup is never left sitting there looking restorable.

The scripts say this and it is worth repeating: **a file on the same disk as
the database is not a backup.** Copy all four files somewhere else, together,
so the dump and the archives you restore from are from the same moment. That
part is yours.

### Proving it

A backup you have not restored is a hypothesis.

```sh
make restore-check
```

That takes the newest dump in `./backups/`, restores it into a scratch database
beside the live one, counts what came back, and drops the scratch database
again. Nothing in production is touched, so there is no excuse for never having
done it. Put it in cron next to the backup.

```
Restored into 'herbology_restore_check'. What came back:
  relation   | count
-------------+-------
 reading     |     0
 site        |     1
 specimen    |     1
 task        |     0
 weather_obs |   500

And the TimescaleDB machinery:
         thing         | count
-----------------------+-------
 background jobs       |     7
 continuous aggregates |     3
 hypertables           |     3
```

It counts the machinery as well as the rows on purpose. A TimescaleDB restore
that skips `timescaledb_post_restore()` produces a database whose row counts
look perfect and which never refreshes a continuous aggregate again. Row counts
alone would not catch it.

### Restoring for real

This overwrites the live database. Take a backup of the current state first,
however broken it is — it is the only copy of what went wrong.

```sh
make backup                                           # the before picture
docker service scale moh_api=0 moh_worker-weather=0 \
  moh_worker-botany=0 moh_worker-hub=0 moh_worker-plates=0

scripts/restore.sh --from backups/moh-herbology-20260924T073519Z.dump \
                   --into herbology --force

docker service scale moh_api=2 moh_worker-weather=1 \
  moh_worker-botany=1 moh_worker-hub=1 moh_worker-plates=1
scripts/migrate.sh status
```

Scaling the application down first is not optional: `--force` drops and
recreates the database, and it cannot do that while the API holds pooled
connections to it. The script terminates the sessions it finds, but a running
API immediately opens more.

Check `migrate.sh status` afterwards. A dump restores whatever schema it
contained, including the ledger, so a backup taken before a migration comes
back needing it again.

### Restoring the pictures

While the services are still scaled to 0, one line per volume, from the
archives taken with the dump you just restored:

```sh
scripts/restore_volume.sh --from backups/moh_plates-images-20260924T073519Z.tar.gz --into moh_plates-images --force
scripts/restore_volume.sh --from backups/moh_grounds-images-20260924T073519Z.tar.gz --into moh_grounds-images --force
scripts/restore_volume.sh --from backups/moh_photos-images-20260924T073519Z.tar.gz --into moh_photos-images --force
```

`--force` empties the volume first; without it the script refuses a volume
that has anything in it, because a restore layered over a half-broken
directory is neither the backup nor the present. A volume that does not
exist yet — a fresh machine — is created. Then scale the services back up.

Skip this step and the restore *looks* complete: the map lists its layers
and the Journal lists its plates, and every picture answers 404. The
contract names that case for both routes, and the troubleshooting entry
below is for the day you see it.

### What is not in the dump, or the archives

Secrets, by design. Keep your certificate and the passwords you generated
wherever you keep such things — a restored database with no
`moh_db_password` is not a recovery.

---

## 14. Two standing rules

These are the operator's to hold as much as the code's, and they are here
rather than buried in a recorded decision because this is where you will see them.

### An MQTT payload never carries a token or an API key

The hub worker publishes readings and states to the broker for Home Assistant
to consume. It does not publish credentials, and nothing you add should either.

This is what makes plain, unencrypted MQTT on port 1883 tolerable on a home
LAN: there is nothing on that topic tree worth stealing. There are readings
worth *forging*, which is why the broker requires a password and why
`allow_anonymous` is off — the dev broker is anonymous because nothing in it is
real, and a broker on a home network with anonymous writes lets anything on
that network invent a soil-moisture reading that the watering schedule
believes.

If you ever find yourself wanting to put a credential in an MQTT payload to
make something work, the something is asking the wrong question.

### A calendar-feed token is the only credential the app itself issues

Every other credential in this system is one you created. The ICS feed tokens
are not: the application generates them, and they are bearer secrets — anyone
holding the URL can read that feed.

Three properties follow, and they are the application's to keep:

* **Never logged.** The token is in the URL, and an access log with tokens in
  it is a credential store nobody remembers to protect — on a self-hosted box,
  the log is usually inside the backup. So the Nginx config turns `access_log`
  off for the two paths that carry one: `/api/v1/calendar/`, where every feed
  is fetched, and `/api/v1/tending/feeds`, whose responses list each feed's
  address. The API redacts the path from its own access log as well, which
  covers running it with no Nginx in front.
* **Never reused across feeds.** One token, one feed.
* **Revoking one must not disturb the others.** Revoke a feed you shared with a
  house-sitter and every other subscription keeps working.

If you proxy this app behind something else, carry both exclusions across:
`/api/v1/calendar/` and `/api/v1/tending/feeds`.

---

## 15. Troubleshooting

### `required variable MOH_REGISTRY is missing a value`

`.env.deploy` does not exist, or does not set it. That is the deploy working as
intended — see [§7](#7-write-your-envdeploy). The message names the variable
and gives an example of its shape.

### `secret not found: moh_ha_token`

Swarm will not start a service referring to a secret that does not exist, even
one you do not use. Create it blank:

```sh
printf '\n' | docker secret create moh_ha_token -
```

`docker secret ls` should show all six from [§6](#6-create-the-secrets).

### Tasks stuck in `Preparing`, or `No such image`

The node cannot pull from your registry. On the node:

```sh
docker service ps --no-trunc moh_api    # the full error
docker pull "$MOH_REGISTRY/moh-api:$MOH_IMAGE_TAG"
```

Usually one of: not logged in on *that* node (`docker login`); a registry with
a certificate the node does not trust; or a plain-HTTP registry that is not in
the node's `insecure-registries`. Credentials are per-node, and `docker stack
deploy --with-registry-auth` forwards the manager's to the workers for the
duration of the deploy.

### `moh-entrypoint: $MOH_DB_PASSWORD_FILE points at /run/secrets/... which is not readable`

The secret is not attached to that service. Check the service actually lists
it:

```sh
docker service inspect moh_api --format '{{json .Spec.TaskTemplate.ContainerSpec.Secrets}}' | tr ',' '\n'
```

If you rotated a secret by hand, the `target=` is probably missing, so the file
landed at its source name instead of the path the stack expects. See
[Rotating a secret](#rotating-a-secret).

### The API restarts in a loop with an authentication failure

The password the database was initialised with and the one the API is sending
have diverged. The database's copy is set **once**, on first initialisation
from an empty volume — changing `moh_db_password` afterwards does not change
the database's own password, only what the clients send.

To fix, change it at the database:

```sh
docker exec -it $(docker ps -qf name=moh_db) \
  psql -U herbology -d herbology -c "ALTER ROLE herbology PASSWORD '<the new one>'"
```

A trailing newline in the secret is the other common cause. The entrypoint
strips them on the client side, but the database's copy came from whatever you
piped into `docker secret create` — which is why [§6](#6-create-the-secrets)
uses `tr -d '\n'`.

### Nginx will not start: `host not found in upstream`

You should not see this — the config names its backends in variables and
resolves them per request precisely so that Nginx starts whether or not the API
is up yet. If you see it, something reintroduced a literal `upstream` block.

### Nginx will not start: `Address family not supported by protocol`

A `listen [::]:80` on a Docker daemon without IPv6. Docker gives containers no
IPv6 address unless configured for it, and Nginx treats that as fatal. The
config ships IPv4-only for this reason; if you added the IPv6 listeners, either
enable IPv6 in the daemon or take them out again.

### 502 from the app, but Nginx is up

That is the design working: Nginx stays up and tells you the backend is not
there. Find out which:

```sh
curl -s  http://localhost/healthz           # nginx itself, on port 80 — should be "ok"
make stack-ps
docker service logs --tail 100 moh_api
docker service logs --tail 100 moh_web
```

### The database healthcheck passes but the API cannot connect

Almost always the first sixty seconds of a brand-new volume. The stack checks
`pg_isready -h 127.0.0.1` rather than the Unix socket for exactly this reason —
the Postgres entrypoint runs a temporary server during initialisation that
listens on the socket only — but the API can still get there first. It
restarts; let it.

### `pg_dump: warning: there are circular foreign-key constraints on this table: hypertable`

Expected, and harmless. TimescaleDB's own catalog tables reference each other,
and `pg_dump` warns about it on every dump. The hint it prints about
`--disable-triggers` applies to data-only dumps; ours is a full dump. Restores
verified fine with the warning present.

### `scripts/migrate.sh` cannot find the database

```
Could not find a running container for the database service 'moh_db' on this node.
```

Either the task is on another node — `docker service ps moh_db` says which, and
you run the script there — or your stack is not called `moh`, in which case set
`MOH_STACK`. To point at one container directly, `MOH_DB_CONTAINER=<id>`.

### `002_rollups.sql has already been applied here, but its contents have changed`

Somebody edited a migration that had already run. `contracts/schema/` is
forward-only and files are never edited after the fact. The runner will not
guess which of the database and the repository is right, and re-running the
file is very unlikely to be the answer. Work out what happened: usually a merge
brought in a changed file, and the fix is a *new* numbered migration.

### Home Assistant shows no entities

In order: is `MOH_HA_BASE_URL` set and reachable *from inside the container*
(`docker exec $(docker ps -qf name=moh_worker-hub) python -c "import
urllib.request;print(urllib.request.urlopen('$MOH_HA_BASE_URL').status)"`); is
the token secret non-blank; did Home Assistant's MQTT integration connect
(`docker service logs moh_mosquitto` shows every connection); and is
`worker-hub` running at all. The Ministry Office screen reports each of these
separately rather than as one "broken".

### 502 on everything, but the backends are healthy and DNS resolves

Symptom: Nginx answers `/healthz` fine, `nslookup api` inside the Nginx
container returns an address, and yet every proxied request logs
`connect() failed (113: Host is unreachable)`. Connecting to a *task* address
works:

```sh
NG=$(docker ps -qf name=moh_nginx | head -1)
docker exec $NG nslookup tasks.api 127.0.0.11     # the individual task IPs
docker exec $NG wget -qO- http://<one of those>:8000/api/v1/healthz
```

If the task address works and the service address does not, the kernel has no
IPVS. Swarm's default `endpoint_mode: vip` gives each service one virtual
address and load-balances it with IPVS; without the `ip_vs` module the DNS
answer is still handed out and the packets go nowhere. Check:

```sh
lsmod | grep ip_vs
ls /proc/net/ip_vs
```

Load it (`modprobe ip_vs`, and make it persistent in `/etc/modules-load.d/`),
or, if you cannot — a container-optimised or minimal-kernel host, some VPS
images, a VM without the module — switch the affected services to DNS
round-robin, which resolves straight to task addresses and needs no IPVS.
Add one line to `.env.deploy` and deploy:

```sh
echo "MOH_ENDPOINT_MODE=dnsrr" >> .env.deploy
make stack-deploy
```

It applies to the five services other services address by name — `api`,
`web`, `db`, `redis`, `mosquitto` — and, being in `.env.deploy`, it holds
across every later deploy. (this was a `docker service update` per
service, which the next `make stack-deploy` quietly undid.)

The stack ships `vip` because it is the swarm default and the right answer on
an ordinary kernel. `dnsrr` loses the stable per-service address and leaves
load balancing to the client's DNS caching, which for this application is a
fair trade.

### A service is stuck, and `make stack-deploy` does not move it

```sh
docker service inspect moh_worker-weather --format '{{.UpdateStatus.State}}'
```

`rollback_paused` or `rollback_completed` means `failure_action: rollback` did
its job — the new tasks never became healthy, so swarm put the previous
version back. That is what you want, except when the previous version is also
broken, which is the case the first time you deploy a fix. The service then
sits on the old image and re-deploying the same tag changes nothing, because
the spec is pinned to the old digest. Push the new image explicitly:

```sh
docker service update --image "$MOH_REGISTRY/moh-worker:$MOH_IMAGE_TAG" moh_worker-weather
```

Tag each build distinctly — which `make push` does — and this is rare.

### The image build fails on `pip install` or `npm ci` with a certificate error

```
SSLError(SSLCertVerificationError(1, '[SSL: CERTIFICATE_VERIFY_FAILED]
  certificate verify failed: self-signed certificate in certificate chain'))
```

Your network re-terminates TLS — a corporate proxy, a filtering appliance, some
VPNs — so the build container sees that appliance's certificate rather than
PyPI's or npm's, and does not trust it. Nothing is wrong with the Dockerfiles;
they trust the public roots their base images ship, which is correct for anyone
not behind such a proxy.

The repository does not carry a workaround, deliberately: baking one
organisation's CA into these images would be both useless and slightly
dangerous everywhere else. Add yours at build time instead, in a copy of the
Dockerfile you keep on your own side:

```dockerfile
# In the Debian-based stages (api, worker):
COPY your-ca.crt /usr/local/share/ca-certificates/your-ca.crt
RUN update-ca-certificates
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
```

`node:22-slim` ships no CA bundle at all, so the web image needs the file
pointed at directly rather than appended to a bundle that does not exist:

```dockerfile
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/your-ca.crt
COPY your-ca.crt /usr/local/share/your-ca.crt
RUN npm config set cafile /usr/local/share/your-ca.crt
```

Both of these were needed to build the images while writing this guide, in an
environment with exactly this kind of proxy, and both worked. They were kept
out of the tree for the reason above.

### The map's layers and the Journal's plates all answer 404

The database knows about pictures that are not on disk. Almost always one of
two things: a restore that brought back the dump and not the volumes — put
them back, [§13](#restoring-the-pictures) — or, on a multi-node swarm, the
API running on a different node from the one that holds the volume (check
`docker service ps moh_api moh_worker-plates`; both are pinned to a manager,
and if you have several managers, the volume is on only one of them).

A 503 rather than a 404 is different: it names `MOH_GROUNDS_IMAGE_DIR` or
`MOH_PLATES_IMAGE_DIR` and means the service has no image directory at all.
The stack sets both; a 503 here means the stack file was edited.

### Something is wrong and you want to start over

Volumes and secrets survive `docker stack rm`. To remove the data too — and
this deletes every plant, reading, plan, plate and photograph:

```sh
docker stack rm moh
sleep 20                               # swarm releases volumes asynchronously
docker volume rm moh_db-data moh_redis-data moh_mosquitto-data \
  moh_grounds-images moh_plates-images moh_photos-images moh_acme
```

---

## 16. What has and has not been executed

the design says a deployment document nobody has executed is a wish list, so
here is the honest accounting. This guide was walked end to end on a
single-node swarm with a stand-in registry, and four defects in it were found
and fixed that way. What follows is what that proved and what it did not.

### Executed, and working

* **Building and pushing all three images**, and deploying them from a
  registry.
* **Every `docker secret create` line in [§6](#6-create-the-secrets)**, run
  verbatim, including the two-secret MQTT dance and the blank
  `moh_ha_token`.
* **`make preflight` and `make stack-deploy`**, from an `.env.deploy` written
  by copying [§7](#7-write-your-envdeploy).
* **Six of the ten services healthy and staying healthy**: `db`, `redis`,
  `mosquitto`, `nginx`, `api` (2 replicas) and `web` (2 replicas).
* **The whole front door.** Plain HTTP redirects 308 to HTTPS; `/healthz`
  answers; the security headers are present; and over TLS both
  `https://.../api/v1/healthz` and the web app return 200. An actual data
  endpoint, `/api/v1/specimens`, returns `{"items":[],...}` — the API in live
  mode, through Nginx, against the real database.
* **[§9](#9-first-run-the-schema), the first-run migration**, against the
  deployed stack. `scripts/migrate.sh` found the database task by itself and
  applied all three files.
* **[§13](#13-backup-and-restore), backup and restore**, against the deployed
  stack: `make backup` then `make restore-check`, with the rows and all the
  TimescaleDB machinery coming back.

### Fixed since that walk, and not re-walked

**The four Arq workers did not start** on the walk above: they exited with
`Error 111 connecting to localhost:6379`, because no worker declared
`redis_settings` and Arq fell back to its default while `MOH_REDIS_URL` went
unread. The maintainers fixed it in `workers/runtime.py`, which every worker's
`WorkerSettings` now goes through. **A deployment with the fix has not been
walked end to end.** Until one is, treat "the workers start" as expected
rather than demonstrated, and `make stack-ps` as the thing that tells you.

### The earlier changes, and what was checked

an earlier release added the two image volumes, the plates worker's mount, the hub worker's
two variables, the volume backup and restore scripts, and the pinning of
the API and the plates worker to a manager ([§4](#4-initialise-a-swarm)).
They were made in a container with the Docker CLI and no daemon, so what
was verified is exactly this and no more:

* **Both files render.** `docker compose config` on the stack file with the
  four required variables, and on the dev compose; the rendered output was
  read back to confirm each service's volumes, environment and placement.
* **The stack still fails by name** without each required variable, and
  `scripts/tests/test_stack_file.py` still passes.
* **Every shell script parses** (`sh -n`), and the two new ones handle their
  arguments as documented; neither has been run against a volume.

Not verified: a deploy, a backup of a real volume, a restore of one, or that
the API serves a plate the worker wrote. Nor that a fresh volume comes up
writable: both Dockerfiles create the mount points owned by `herbology` so
that Docker seeds a new volume with that ownership, which is Docker's
documented behaviour and not something a container without a daemon can
demonstrate. the earlier drill is where all of that happens.

### Verified only under a caveat

**Service virtual addresses.** The machine this was walked on runs a minimal
kernel with no `ip_vs` module, so swarm's default VIP load balancing
black-holes every service-to-service connection while DNS still answers. The
overlay data plane itself is fine: task addresses work. Switching the five
services to `endpoint_mode: dnsrr` made everything above pass. On an ordinary
Linux host with `ip_vs` present, the shipped `vip` mode is the right default
and none of this applies — but it means VIP mode specifically has not been
exercised here. See the troubleshooting entry on 502s if you meet it.

**The images were built through a TLS-intercepting proxy.** The environment
this was walked in re-terminates TLS, so `pip install` and `npm ci` could not
verify PyPI or npm without that proxy's CA. The Dockerfiles in the tree are
unmodified — the CA went into a throwaway copy, never here, because one
organisation's CA baked into these images helps nobody else. If your network
does the same thing you will meet it too, and the troubleshooting section has
the two stanzas that worked. Nothing about it reaches what you build
otherwise.

### Not executed at all

* **A multi-node swarm.** Everything ran on one node, so the placement
  constraints, `--with-registry-auth` and host-mode ports across several nodes
  are reasoned about rather than demonstrated.
* **A real certificate.** A self-signed one was used throughout, so the ACME
  paths in [§5](#5-certificates) and the renewal procedure in
  [§12](#12-upgrading) are untested.
* **A real Home Assistant.** [§11](#11-connecting-home-assistant) is written
  from the adapter's configuration and Home Assistant's documented UI, not
  from a running instance.
* **An upgrade between two real releases**, and a rollback.
* **A restore of the picture volumes**, with the map and the Journal checked
  afterwards. The scripts exist; the drill is the earlier.

If you hit something this guide does not cover, that is a gap worth reporting
rather than working around silently.
