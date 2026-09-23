# hashi — the env-file gate. Sourced, never executed.
#
# WHAT: one function, `env_file_must_be_readable`, which asks compose whether it can PARSE
#       the env file and, when it cannot, says the file and compose's own line number and
#       nothing else.
# WHY:  compose is the ONE thing allowed to open the env file (CLAUDE.md, hard rules), and
#       when it cannot parse that file it quotes the offending line's whole value straight
#       back: `unterminated quoted value "…"`, `Invalid template: "…"`, `unexpected
#       character … in variable name "…"`. The line it is complaining about is as likely to
#       be HASHI_SECRET_KEY or POSTGRES_PASSWORD as anything else.
#
#       M28.7 found that in `scripts/backup.sh`, where the output of a failed run is what
#       cron mails — one stray quote put the master key in a mail spool, six times a day,
#       for as long as the file stayed wrong. M28.8 found the same complaint reaching the
#       terminal from `scripts/panel-bootstrap.sh`, whose `compose up -d --build` output is
#       printed as it comes. That one is not cron's mail; it is worse in a different way,
#       because the output of a failed INSTALL is exactly what somebody pastes into a chat
#       window when asking why their install did not work.
#
#       THE FUNCTION IS A LIBRARY RATHER THAN A COPY, and that is the decision: two
#       scrubbers are two things that drift, and the next printer added to either script
#       would be behind whichever one its author remembered. One implementation, two
#       callers, one place to be right.
#
#       WHAT MAKES IT SAFE IS STRUCTURAL, and it is the property to preserve in both
#       callers: it runs BEFORE any compose call the script can reach — from the dispatch
#       in `backup.sh`, from the top of section 1 in `panel-bootstrap.sh` — so every such
#       call is behind it, however many there come to be. Do not turn this into a count of
#       call sites to check against, do not move it inside a verb, and do not "simplify" it
#       to scrubbing at each printer.
#
#       What is repeated: the file, and compose's own line number, out of a DIGITS-ONLY
#       capture so that nothing of the operator's file can ride along inside what looks
#       like a number. What is never repeated: the text on that line. Compose's complaint
#       is captured and dropped, not printed.
#
#       Any other refusal — `error while interpolating … required variable X is missing a
#       value` — names variables and never values, so it passes through untouched and an
#       operator with a genuinely missing variable is still told which one.
# HOW:  the caller defines `ENV_FILE` and a `COMPOSE` array, then sources this file and
#       calls the function. It deliberately uses the CALLER's own compose invocation, so
#       what is tested is the command that script is about to make rather than a second
#       one assembled here.
#
#       `ENV_GATE_NOTHING_HAPPENED` is the one sentence that differs between callers —
#       what the refusal promises was not done. Its default is `backup.sh`'s, which M28.7
#       pinned; `panel-bootstrap.sh` sets its own before sourcing.

ENV_GATE_NOTHING_HAPPENED="${ENV_GATE_NOTHING_HAPPENED:-Nothing was dumped, written or sent.}"

env_file_must_be_readable() {
  [ -n "${ENV_FILE:-}" ] && [ "${#COMPOSE[@]}" -gt 0 ] || {
    echo "env-file-gate.sh was sourced without ENV_FILE and COMPOSE — this is a bug in" >&2
    echo "the script that sourced it, not in the operator's env file." >&2
    exit 1
  }

  local complaint first line=""
  if complaint="$("${COMPOSE[@]}" config --quiet 2>&1)"; then return 0; fi
  # Any other refusal is about the compose files or an unset variable — it names variables
  # and never values, and the caller reports it itself with its own advice attached.
  case "${complaint}" in "failed to read "*) ;; *) return 0 ;; esac

  # Digits only, out of a regex capture, so nothing of the operator's file can ride along
  # in what looks like a number. The leftmost match is structurally the real one: compose's
  # `failed to read <path>: line N:` prefix always precedes attacker-controlled content.
  first="${complaint%%$'\n'*}"
  [[ "${first}" =~ :\ line\ ([0-9]+): ]] && line=", at line ${BASH_REMATCH[1]},"

  cat >&2 <<MSG
the env file at ${ENV_FILE}${line} is one compose cannot read.

${ENV_GATE_NOTHING_HAPPENED} What compose said about that line is deliberately NOT
repeated here: it quotes the line's whole value back, that value may be HASHI_SECRET_KEY or
POSTGRES_PASSWORD, and this text is what cron mails when a scheduled run fails and what an
operator pastes into a chat window when an install fails. Open the file and look: an
unclosed quote, a key with a space in it, or a stray dollar sign is what produces this.
MSG
  exit 1
}
