# The Ministry of Herbology. The deployment owns this file.
COMPOSE := docker compose -f infra/compose/docker-compose.dev.yml
VENV    := .venv
PY      := $(VENV)/bin/python

# --- Deployment ---------------------------------------------------------------
#
# Everything below is parameters, never values. `make images` and `make push`
# need MOH_REGISTRY; `make stack-deploy` needs the rest, and reads them from
# MOH_ENV_FILE. docs/deploy/README.md is the guide.

STACK_FILE  := infra/stack/docker-stack.yml
MOH_STACK   ?= moh
MOH_ENV_FILE ?= .env.deploy
# `always` asks the registry for each image's digest, so every node runs the
# same bytes. On one machine with no registry there is nothing to ask and the
# deploy fails; `make stack-deploy MOH_RESOLVE_IMAGE=never` is that case
# (guide §3). The guide said to edit this file instead.
MOH_RESOLVE_IMAGE ?= always

# The tag identifies the source it was built from, or the build fails. A dirty
# tree gets a -dirty suffix, so an image whose contents nobody can reconstruct
# cannot be quietly pushed under a clean-looking tag.
GIT_SHA         := $(shell git rev-parse --short=12 HEAD 2>/dev/null)
GIT_DESCRIBE    := $(shell git describe --tags --always --dirty 2>/dev/null)
MOH_IMAGE_TAG   ?= $(GIT_DESCRIBE)
BUILD_TIMESTAMP := $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
IMAGES          := api web worker

.PHONY: help dev down logs fixtures test test-api test-web lint types format check contract
.PHONY: stack-check tool-versions a11y
.PHONY: images push preflight stack-config stack-deploy stack-rm stack-ps
.PHONY: migrate migrate-status backup backup-volumes restore-check

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

dev: ## Bring up the local stack (db, redis, mqtt, api, worker, web)
	$(COMPOSE) up --build -d
	@echo "API  http://localhost:8000/api/v1/docs"
	@echo "Web  http://localhost:5173"

down: ## Stop the local stack
	$(COMPOSE) down

logs: ## Follow the stack's logs
	$(COMPOSE) logs -f

fixtures: ## Load fixture data into the dev database
	$(COMPOSE) exec -T db psql -U herbology -d herbology -c 'SELECT 1' >/dev/null
	$(PY) scripts/load_fixtures.py

$(VENV):
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -e 'api[dev]'

# --- Tests and lint ------------------------------------------------------------
#
# These targets mirror .github/workflows/ci.yml, job by job, and the workflow
# is the source of truth: when it changes, this changes with it, or a
# parts of the project that runs `make test` sees something CI will not. This
# target ran `pytest tests` alone, while CI collected four trees and linted a
# fourth, so a branch could be green here and red there.
#
#   contract the Contract job pytest tests/contract, then actionlint
#   lint the API job's Lint ruff + black over api workers tests scripts,
#              and the Web job's lint prettier + svelte-check
#   types the API job's Types mypy api/app workers api/inventory (required),
#                                      then api/tending (advisory, as in CI)
#   test-api the API job's Tests pytest tests api workers scripts (root pytest.ini)
#   test-web the Web job's tests vitest, then the production build
#   a11y the Accessibility job scripts/a11y.sh: build, mock API, the WCAG AA audit
#   stack-check the Deployment stack job
#
# `make test` runs the first five. `make check` adds the last two: the audit
# starts the mock API and a browser and takes a few minutes, and stack-check
# needs Docker. Run them before a PR that touches the web app or the stack;
# CI runs them on every PR regardless.
# The two jobs this does not reproduce: Build images (docker build of the
# three Dockerfiles, which `make images` does with a registry of your own) and
# Directory ownership, which is about a branch rather than a tree:

# The ruff and black that run here are the ones api/pyproject.toml pins, or
# the run stops and says so. A .venv built before the pin changed keeps its
# old ruff silently otherwise, which is the drift this exists to catch.
RUFF_PIN  := $(shell sed -n 's/^ *"ruff==\([^"]*\)".*/\1/p' api/pyproject.toml)
BLACK_PIN := $(shell sed -n 's/^ *"black==\([^"]*\)".*/\1/p' api/pyproject.toml)

tool-versions: $(VENV) ## The venv's ruff and black are the versions pyproject pins
	@test -n "$(RUFF_PIN)" -a -n "$(BLACK_PIN)" || { \
	  echo "api/pyproject.toml no longer pins ruff and black with ==. It must."; exit 1; }
	@have=$$($(VENV)/bin/ruff --version | sed 's/^ruff //'); \
	test "$$have" = "$(RUFF_PIN)" || { \
	  echo "ruff $$have is installed; api/pyproject.toml pins $(RUFF_PIN), which is what CI runs."; \
	  echo "  $(VENV)/bin/pip install -e 'api[dev]'"; exit 1; }
	@have=$$($(VENV)/bin/black --version | sed -n '1s/^black, \([^ ]*\).*/\1/p'); \
	test "$$have" = "$(BLACK_PIN)" || { \
	  echo "black $$have is installed; api/pyproject.toml pins $(BLACK_PIN), which is what CI runs."; \
	  echo "  $(VENV)/bin/pip install -e 'api[dev]'"; exit 1; }

test: contract lint types test-api test-web ## What CI runs: contract, lint, types, every pytest tree, the web suite

# CI also points MOH_TEST_DATABASE_URL at a Postgres service, so the three
# live-repository suites run there; here they skip unless you set it to a
# database they may create tables in (api/tending/README.md shows the line).
test-api: $(VENV) ## pytest over the four trees CI collects (root pytest.ini)
	$(PY) -m pytest tests api workers scripts -q

test-web: ## The web job after its lint: vitest, then the production build
	cd web && npm run test && npm run build

contract: $(VENV) ## Contract tests, and actionlint over the workflow — the CI Contract job
	$(PY) -m pytest tests/contract -q
	$(VENV)/bin/actionlint -shellcheck= -pyflakes= .github/workflows/ci.yml

lint: tool-versions ## Lint everything, exactly what CI lints
	$(VENV)/bin/ruff check api workers tests scripts
	$(VENV)/bin/black --check api workers tests scripts
	cd web && npm run lint

types: $(VENV) ## mypy, exactly as CI: three trees required, api/tending advisory
	$(VENV)/bin/mypy api/app workers api/inventory
	-$(VENV)/bin/mypy api/tending

format: $(VENV) ## Format everything
	$(VENV)/bin/ruff check --fix api workers tests scripts
	$(VENV)/bin/black api workers tests scripts
	cd web && npm run format

check: test a11y stack-check ## Everything CI runs that a tree can answer for: tests, the audit, the stack

a11y: $(VENV) ## The CI Accessibility job: build the web app, start the mock API, run the WCAG AA audit
	MOH_PYTHON=$(PY) scripts/a11y.sh

# The Deployment stack job: the stack renders with the four required
# variables supplied, refuses by name without each, the nginx configuration
# passes `nginx -t`, and every shell script parses. Needs docker; the nginx
# check needs a daemon and is skipped with a note when there is none.
stack-check: ## The CI "Deployment stack" job: render, required-by-name, nginx -t, sh -n
	@MOH_REGISTRY=registry.example.net/ministry-of-herbology MOH_IMAGE_TAG=check \
	 MOH_PUBLIC_BASE_URL=https://herbology.example.net \
	 MOH_NWS_USER_AGENT='ministry-of-herbology (check@example.net)' \
	 docker compose -f $(STACK_FILE) config >/dev/null && echo "stack: renders"
	@for missing in MOH_REGISTRY MOH_IMAGE_TAG MOH_PUBLIC_BASE_URL MOH_NWS_USER_AGENT; do \
	  output=$$( \
	    export MOH_REGISTRY=registry.example.net/moh MOH_IMAGE_TAG=check; \
	    export MOH_PUBLIC_BASE_URL=https://example.net; \
	    export MOH_NWS_USER_AGENT="moh (check@example.net)"; \
	    unset "$$missing"; \
	    docker compose -f $(STACK_FILE) config 2>&1 >/dev/null) || true; \
	  case "$$output" in \
	    *"$$missing"*) echo "stack: $$missing is required and named" ;; \
	    *) echo "stack: $$missing did not fail by name. Got: $$output"; exit 1 ;; \
	  esac; \
	done
	@if docker info >/dev/null 2>&1; then \
	  tmp=$$(mktemp -d); \
	  openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
	    -keyout "$$tmp/key.pem" -out "$$tmp/cert.pem" -subj '/CN=check.example.net' 2>/dev/null; \
	  docker run --rm \
	    -v "$$PWD/infra/stack/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
	    -v "$$PWD/infra/stack/nginx/moh-proxy.conf:/etc/nginx/moh-proxy.conf:ro" \
	    -v "$$tmp/cert.pem:/run/secrets/moh_tls_cert:ro" \
	    -v "$$tmp/key.pem:/run/secrets/moh_tls_key:ro" \
	    nginx:1.27-alpine nginx -t; \
	  rm -rf "$$tmp"; \
	else \
	  echo "stack: no docker daemon here, so nginx -t was not run (CI runs it)"; \
	fi
	@for script in scripts/*.sh scripts/lib/*.sh scripts/ci/*.sh infra/docker/entrypoint.sh; do \
	  sh -n "$$script" || exit 1; \
	done; echo "stack: all shell scripts parse"

# ------------------------------------------------------------------------------
# Deployment. See docs/deploy/README.md.
# ------------------------------------------------------------------------------

# MOH_REGISTRY is your registry and your namespace, with no trailing slash:
#   registry.example.net/ministry-of-herbology, ghcr.io/you, localhost:5000/moh
require-registry:
	@test -n "$(MOH_REGISTRY)" || { \
	  echo "MOH_REGISTRY is not set."; \
	  echo "It is your registry and namespace, with no trailing slash, e.g."; \
	  echo "  make push MOH_REGISTRY=registry.example.net/ministry-of-herbology"; \
	  exit 1; }

require-clean-tree:
	@test -z "$$(git status --porcelain 2>/dev/null)" || test -n "$(MOH_ALLOW_DIRTY)" || { \
	  echo "The working tree has uncommitted changes, so $(MOH_IMAGE_TAG) would not"; \
	  echo "identify what is in the image. Commit them, or accept that by setting"; \
	  echo "MOH_ALLOW_DIRTY=1."; \
	  exit 1; }

images: require-registry ## Build the three images, tagged from the commit
	@echo "Building $(MOH_IMAGE_TAG) for $(MOH_REGISTRY)"
	@for image in $(IMAGES); do \
	  echo "  moh-$$image"; \
	  docker build \
	    --file infra/docker/$$image.Dockerfile \
	    --tag "$(MOH_REGISTRY)/moh-$$image:$(MOH_IMAGE_TAG)" \
	    --label org.opencontainers.image.title="ministry-of-herbology-$$image" \
	    --label org.opencontainers.image.revision="$(GIT_SHA)" \
	    --label org.opencontainers.image.version="$(MOH_IMAGE_TAG)" \
	    --label org.opencontainers.image.created="$(BUILD_TIMESTAMP)" \
	    --label org.opencontainers.image.source="https://github.com/mtaylor45/Ministry-of-Herbology-V1.0.0" \
	    . || exit 1; \
	done
	@echo
	@echo "Built:"
	@for image in $(IMAGES); do echo "  $(MOH_REGISTRY)/moh-$$image:$(MOH_IMAGE_TAG)"; done

push: require-registry require-clean-tree images ## Build, then push to MOH_REGISTRY
	@for image in $(IMAGES); do \
	  echo "pushing moh-$$image"; \
	  docker push "$(MOH_REGISTRY)/moh-$$image:$(MOH_IMAGE_TAG)" || exit 1; \
	done
	@echo
	@echo "Deploy this build with:  MOH_IMAGE_TAG=$(MOH_IMAGE_TAG) make stack-deploy"

# The deploy is detached, and scripts/stack_wait.sh then waits for every
# service to run what it should, within MOH_DEPLOY_TIMEOUT seconds (default
# 600), and says what is not running and why if it does not. This
# was `--detach=false`, which waited for ever on a crash-looping service and,
# CI, on a healthy stack too.
#
# Every moh_caldav_<feed_id> secret in the swarm goes onto the API through a
# generated overlay (scripts/caldav_overlay.sh): `docker stack deploy` resets a
# service to what its files list, and would otherwise drop the per-feed
# calendar credentials an operator added with --secret-add (guide §11).
#
# `docker stack deploy` interpolates from the shell and has no --env-file, so
# the file has to reach the environment somehow. Not by sourcing it: the very
# first value this project asks for, MOH_NWS_USER_AGENT, contains parentheses,
# and `. ./.env.deploy` dies on them with an error naming neither the file nor
# the line. scripts/with_env.sh reads KEY=VALUE and evaluates nothing.
WITH_ENV := scripts/with_env.sh $(MOH_ENV_FILE) --

# The stack file's own `:?` messages have to stay terse and hyphen-free, or
# `docker stack deploy` silently substitutes part of the message (see the
# comment at the top of the stack file). The readable version lives here.
preflight: ## Check that everything the deploy needs is present
	@$(WITH_ENV) sh -c '\
	  fail=0; \
	  for v in MOH_REGISTRY MOH_IMAGE_TAG MOH_PUBLIC_BASE_URL MOH_NWS_USER_AGENT; do \
	    eval "value=\$$$$v"; \
	    [ -n "$$value" ] && continue; \
	    fail=1; \
	    case $$v in \
	      MOH_REGISTRY) echo "MOH_REGISTRY: your registry and namespace, no trailing slash." ;; \
	      MOH_IMAGE_TAG) echo "MOH_IMAGE_TAG: the tag to run. make push prints the one it built." ;; \
	      MOH_PUBLIC_BASE_URL) echo "MOH_PUBLIC_BASE_URL: the https:// URL the app is reached on, no trailing slash." ;; \
	      MOH_NWS_USER_AGENT) echo "MOH_NWS_USER_AGENT: a contact address. The US weather service refuses traffic without one." ;; \
	    esac; \
	  done; \
	  if [ $$fail -ne 0 ]; then \
	    echo; echo "Set these in $(MOH_ENV_FILE). docs/deploy/README.md section 7."; \
	    exit 1; \
	  fi; \
	  echo "Required variables: all four present."'
	@$(WITH_ENV) sh -c '\
	  missing=""; \
	  for s in "$${MOH_DB_PASSWORD_SECRET:-moh_db_password}" \
	           "$${MOH_MQTT_PASSWORD_SECRET:-moh_mqtt_password}" \
	           "$${MOH_MQTT_PASSWORDS_SECRET:-moh_mqtt_passwords}" \
	           "$${MOH_HA_TOKEN_SECRET:-moh_ha_token}" \
	           "$${MOH_TLS_CERT_SECRET:-moh_tls_cert}" \
	           "$${MOH_TLS_KEY_SECRET:-moh_tls_key}"; do \
	    docker secret inspect "$$s" >/dev/null 2>&1 || missing="$$missing $$s"; \
	  done; \
	  if [ -n "$$missing" ]; then \
	    echo "Missing swarm secret(s):$$missing"; \
	    echo "docs/deploy/README.md section 6 gives the command for each; a"; \
	    echo "MOH_*_SECRET line in $(MOH_ENV_FILE) names a rotated one (section 12)."; \
	    exit 1; \
	  fi; \
	  echo "Swarm secrets: all six present."'

stack-config: ## Render the stack with your variables filled in, and check it
	@$(WITH_ENV) docker compose -f $(STACK_FILE) config

stack-deploy: preflight ## Deploy or update the stack (reads MOH_ENV_FILE)
	@test -f "$(MOH_ENV_FILE)" || { \
	  echo "$(MOH_ENV_FILE) does not exist."; \
	  echo "Copy the deployment section of .env.example into $(MOH_ENV_FILE) and"; \
	  echo "fill it in — every value is yours to choose. docs/deploy/README.md"; \
	  echo "walks through it."; \
	  exit 1; }
	@overlay=$$(mktemp); \
	docker secret ls --format '{{.Name}}' | scripts/caldav_overlay.sh > "$$overlay"; \
	if [ -s "$$overlay" ]; then \
	  echo "Calendar push: keeping $$(grep -c '^  moh_caldav_' "$$overlay") feed secret(s) on the API."; \
	else rm -f "$$overlay"; overlay=""; fi; \
	MOH_CALDAV_OVERLAY="$$overlay" MOH_FALLBACK_TAG="$(MOH_IMAGE_TAG)" $(WITH_ENV) sh -c '\
	  MOH_IMAGE_TAG="$${MOH_IMAGE_TAG:-$$MOH_FALLBACK_TAG}"; \
	  export MOH_IMAGE_TAG; \
	  docker stack deploy \
	    --detach=true \
	    --resolve-image=$(MOH_RESOLVE_IMAGE) \
	    -c $(STACK_FILE) $${MOH_CALDAV_OVERLAY:+-c "$$MOH_CALDAV_OVERLAY"} "$(MOH_STACK)"'; \
	status=$$?; [ -z "$$overlay" ] || rm -f "$$overlay"; \
	[ $$status -eq 0 ] || exit $$status; \
	MOH_STACK="$(MOH_STACK)" scripts/stack_wait.sh

stack-ps: ## What the stack is doing
	@docker stack ps "$(MOH_STACK)" \
	  --format 'table {{.Name}}\t{{.Node}}\t{{.CurrentState}}\t{{.Error}}'

stack-rm: ## Remove the stack. Volumes and secrets survive this.
	docker stack rm "$(MOH_STACK)"

migrate-status: ## Which schema migrations have run against the live database
	@MOH_STACK="$(MOH_STACK)" scripts/migrate.sh status

migrate: ## Apply pending schema migrations to the live database
	@MOH_STACK="$(MOH_STACK)" scripts/migrate.sh apply

backup: ## Dump the live database and archive the image volumes into ./backups/
	@MOH_STACK="$(MOH_STACK)" scripts/backup.sh
	@MOH_STACK="$(MOH_STACK)" scripts/backup_volumes.sh

backup-volumes: ## Archive the three image volumes only (the database is `make backup`)
	@MOH_STACK="$(MOH_STACK)" scripts/backup_volumes.sh

restore-check: ## Prove the newest backup by restoring it into a scratch database
	@dump=$$(ls -t backups/*.dump 2>/dev/null | head -n 1); \
	test -n "$$dump" || { echo "No backup in ./backups/. Run: make backup"; exit 1; }; \
	echo "Restoring $$dump into a scratch database"; \
	MOH_STACK="$(MOH_STACK)" scripts/restore.sh --from "$$dump"
