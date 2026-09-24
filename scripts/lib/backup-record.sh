# hashi — the backup record, read once and in one place. Sourced, never executed.
#
# WHAT: one entry point, `backup_record_read FILE`, which answers with EITHER a refusal —
#       `RECORD_FAULT`, the name of the thing that made the file unreadable — OR a
#       validated reading of it, in the `READING_*` variables below. Nothing else on this
#       host opens that file, and nothing anywhere gets a value out of it without the
#       validation having passed first.
# WHY:  M28 was blocked twice and reviewed into four more instances of ONE defect: several
#       independent readers of one file, each deciding for itself what that file entitles
#       it to say. `scripts/backup-run.sh` alone held two of them — a lenient one behind
#       `tick` and `now`, which pulled fields out of whatever was at the path and never
#       checked anything, and a strict one behind `status` and `due`, which refused the
#       same file by name. So a record with a damaged `last_attempt` made `tick` conclude
#       the day's backup had been taken — out of a file it could not parse, and about which
#       the panel said in as many words that nothing could be assumed. The channel that
#       actually takes backups was the one that believed the file.
#
#       WHAT THIS IS NOT: a record dated AHEAD of this host's clock is not this defect and
#       is not closed by this library. That record is valid — every reader parses it and
#       they agree about it — so it arrives here as a reading, and everything that then
#       happens to it happens in `scripts/backup-run.sh`: `decide` takes a backup on a due
#       date ahead of the clock (M28.19), `due` exits 1, and the panel goes loud only when
#       a RUN TIMESTAMP is ahead — `control/app/services/backups.py::_ahead` reads
#       `last_success` and `last_failure` and never `due_date`, by its own documented
#       design, so a record whose due date alone is ahead draws no banner at all. Verified
#       by reading both records through that module. Do not read the paragraph above as
#       having covered any of it.
#
#       That is the shape M28.12 named and M28.13 closed one level down, in
#       `scripts/lib/env-value.sh`, and the lesson is the same: the defect was never one
#       bad comparison, it was a second parser that gives the right answer on every file
#       anybody tests with. A library rather than a tidier `backup-run.sh`, for the reason
#       the other two libraries here exist: two parsers are two things that drift, and they
#       drift silently.
#
#       WHAT THE COLLAPSE IS. There is still more than one EXTRACTOR in this file — a
#       value reader, a raw-text reader, a date scraper — because the record holds three
#       shapes of thing. What there is no longer is a second WAY IN: the bytes are read
#       once, canonicalised once, validated once, and the reading is assembled in the same
#       pass, so no caller can reach a value the validation refused. That is the property
#       the verbs used to differ on, and `tests/infra/test_what_the_command_line_may_say_
#       about_a_backup.py` holds it structurally rather than by inspection.
#
#       WHAT A REFUSAL MEANS TO A CALLER, settled by the owner on 2026-09-24 and written
#       down in docs/decisions.md: a record `tick` cannot read is NO RECORD. `tick` and
#       `now` proceed on the empty reading and take a backup; `status` and `due` refuse.
#       The fail-safe direction — a reader that cannot parse the file must not conclude the
#       day's backup was taken, and the only other answer, refusing to run, stops backups
#       on the strength of a file the product itself cannot understand. The cost, accepted
#       knowingly: a damaged record triggers a dump rather than suppressing one.
# HOW:  `. "${REPO_ROOT}/scripts/lib/backup-record.sh"`, then:
#
#         if backup_record_read "${STATE_FILE}"; then   # a reading (possibly "no record")
#           … READING_LAST_AT …
#         else                                          # a refusal, and nothing was read
#           … "${RECORD_FAULT}" …
#         fi
#
#       The FILE IS AN ARGUMENT, as in `scripts/lib/env-value.sh` and unlike
#       `scripts/lib/env-file-gate.sh`: this is pure reading and the path belongs to the
#       caller, which is the one that also writes there.
#
#       It is called ONCE per run, in the caller's own shell — never as `$(…)`. That is not
#       style: `record_problem` used to be called that way and every variable it set while
#       reading the file died with the subshell, which is why the size refusal had to go
#       back and measure the file a second time (M28.17). Facts gathered during the read —
#       how big the file was, what shape was at the path — survive here because there is no
#       subshell to lose them in.

# The most of that file anything will ever read, the same number as
# control/app/services/backups.py's MOST_OF_A_RECORD and refused the same way: a file
# larger than this is REFUSED WHOLE, naming its size, and not one byte of it is read out as
# fact. The real thing is well under a kilobyte, so anything near this is a wrong path — a
# mount pointing somewhere else, a log file — rather than a record with too much in it.
#
# Reading the first 64 KiB and judging THAT is the rejected alternative, written down
# because it is tempting: it is a verdict about a file nobody has seen all of, and a record
# whose first 64 KiB happen to parse would be read out as fact. The comment here said
# "truncated at the ceiling and then refused for its missing end" until review found that
# claim was not true — the truncation was silent, what survived it sometimes parsed, and the
# answer then varied between runs of the same command. A comment describing a refusal the
# code does not perform is the same defect as a screen describing a backup that did not
# happen, which is why the sentence is kept rather than quietly deleted with the code.
#
# "THE SAME NUMBER" IS HELD BY A TEST rather than by this sentence:
# tests/infra/test_the_command_line_says_what_the_panel_says.py reads the assignment below,
# the panel's own `MOST_OF_A_RECORD` out of its source, and the number in
# docs/deploy/runbook.md's prose, and fails when any two of them differ. Until M28.17 the
# parity was a promise in a comment — move one side and the two channels give different
# verdicts about one file, with nothing going red, which is the defect this whole milestone
# is about, re-entering as documentation.
MOST_OF_A_RECORD=65536

# The record's own version, read here and WRITTEN by scripts/backup-run.sh out of this same
# name, so a writer that starts writing a new shape cannot forget to tell the reader.
RECORD_SCHEMA=1

# The longest string this will repeat out of the record, exactly as
# control/app/services/backups.py's ``_text``. A value over it is a record this refuses
# rather than a line it truncates.
LONGEST_VALUE=200
# The two shapes every date in the record has. Checked rather than trusted because these
# are printed on a terminal and because a file on a disk is where a hand edit goes.
A_TIMESTAMP='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'
A_DATE='^[0-9]{4}-[0-9]{2}-[0-9]{2}$'

# --- what the entry point answers with ----------------------------------------------------

# Whether there is anything at all at the path. "Nothing there" is not a fault: a host that
# has never run a backup is entitled to that state, and refusing it would stop the first
# backup of every new install.
RECORD_PRESENT=""
# Empty when the reading below is valid; otherwise the name of what made the file
# unreadable. Every name but two is a KEY of the record. `shape` and `size` are faults that
# have no key — nothing was read out of a directory and nothing was read out of an
# over-large file — and each needs its own sentence wherever it is reported, or the refusal
# accuses the record of a key it has never had (M28.17).
RECORD_FAULT=""
# What is at the path, in words an operator can act on, when the fault is `shape`. Gathered
# during the read, which is the only moment it is knowable without asking twice.
RECORD_SHAPE=""
# How big the file was, when the fault is `size`. A byte count is a fact ABOUT the file and
# not one of its contents, which is the line every message about this record stays on the
# safe side of.
RECORD_BYTES=""

# The reading. These are the values the record is entitled to be believed about, and they
# are only ever assigned after the validation above has passed.
#
# THE SCHEDULE'S OWN THREE — `due_date`, `attempts`, `retry_not_before` — are read but NOT
# validated, and that is deliberate rather than an omission. The panel does not read them at
# all (control/app/services/backups.py::_parse), so validating them here would refuse a file
# the panel reads happily, which is the two-channels-disagree defect arriving from the
# strict side. They are coerced where they are used instead: a count through `_record_number`
# because `$(( ))` reads `08` as octal and dies.
READING_DUE_DATE=""
READING_ATTEMPTS=0
READING_RETRY_AT=""
READING_OFFSITE=""
READING_MISSED_DATES=""
READING_MISSED_TOTAL=0
READING_LAST_AT=""; READING_LAST_DUE=""; READING_LAST_CODE=0; READING_LAST_OUTCOME=""
READING_OK_AT=""; READING_OK_DUE=""; READING_OK_CODE=0; READING_OK_OUTCOME=""
READING_BAD_AT=""; READING_BAD_DUE=""; READING_BAD_CODE=0; READING_BAD_OUTCOME=""

# The record's text, canonicalised, held in this library and nowhere else. A reader outside
# it would be the second parser all over again, so `tests/infra/` fails if `${RECORD}`
# appears in any other script.
RECORD=""

_record_forget() {
  RECORD=""; RECORD_PRESENT=""; RECORD_FAULT=""; RECORD_SHAPE=""; RECORD_BYTES=""
  READING_DUE_DATE=""; READING_ATTEMPTS=0; READING_RETRY_AT=""
  READING_OFFSITE=""; READING_MISSED_DATES=""; READING_MISSED_TOTAL=0
  READING_LAST_AT=""; READING_LAST_DUE=""; READING_LAST_CODE=0; READING_LAST_OUTCOME=""
  READING_OK_AT=""; READING_OK_DUE=""; READING_OK_CODE=0; READING_OK_OUTCOME=""
  READING_BAD_AT=""; READING_BAD_DUE=""; READING_BAD_CODE=0; READING_BAD_OUTCOME=""
}

# --- the one entry point ------------------------------------------------------------------

# Read the record at FILE. 0 and a reading, or 1 and `RECORD_FAULT`.
backup_record_read() {
  local file="$1" size
  _record_forget

  # `-e` and then `-f`, not `-f` alone. A DIRECTORY at this path is presence, not absence,
  # and `[ -f ]` reads it as absence — so this channel answered "no backup has ever been
  # recorded on this host" about a path with something in it while the panel, whose
  # `S_ISREG` check refuses a directory, a FIFO, a socket and a device alike, answered
  # UNREADABLE about the same path. Two channels, one path, two verdicts (M28.17).
  # A dangling symlink stays ABSENCE on both sides: `-e` follows it and finds nothing,
  # exactly as the panel's `open()` raises FileNotFoundError.
  [ -e "${file}" ] || return 0
  RECORD_PRESENT="yes"
  if [ ! -f "${file}" ]; then
    RECORD_SHAPE="$(_record_shape_at "${file}")"
    RECORD_FAULT="shape"
    return 1
  fi

  # OVER THE CEILING IS NOT THE RECORD, and it is refused before it is opened.
  size="$(wc -c < "${file}" | tr -cd '0-9')"
  if [ -n "${size}" ] && [ "${size}" -gt "${MOST_OF_A_RECORD}" ]; then
    RECORD_BYTES="${size}"
    RECORD_FAULT="size"
    return 1
  fi

  RECORD="$(_record_as_lines < "${file}")"
  RECORD_FAULT="$(_record_problem)"
  [ -z "${RECORD_FAULT}" ] || return 1
  _record_capture
}

# What is at the record's path when it is not the record, in the words an operator can act
# on. A DIRECTORY is the one that really happens: `mkdir` of the file's own name, or a bind
# mount in a compose file naming the FILE instead of the directory it is in, which the
# docker daemon then creates as a directory. The other shapes are named generically because
# the remedy is the same and the fault is not.
_record_shape_at() {
  if [ -d "$1" ]; then
    printf 'a directory'
  else
    printf 'something that is not a file'
  fi
}

# --- the bytes, canonicalised -------------------------------------------------------------

# The record with every TOP-LEVEL key on a line of its own, whatever layout it is in on
# disk. Read once into `RECORD`; every reader below works on that text rather than on the
# file, so there is exactly one place that decides what the bytes are.
#
# WHY IT EXISTS (M28.15, found in acceptance round 2). Every reader here is a `sed` over
# lines, because a host that can run the stack is not assumed to have a JSON parser — the
# control plane is the one machine that may have to be rebuilt from nothing. That is still
# right, and it had one consequence nobody meant: a record that had merely been
# RE-INDENTED — run through `jq .`, or opened and saved by anything that pretty-prints —
# put each nested key on its own line, and this reader called a perfectly good record
# damaged. The panel reads the same file with `json.loads`, which does not care where the
# line breaks are, so the two channels disagreed about one file again.
#
# LAYOUT IS THE ONLY THING THIS TOLERATES, and that is deliberate. Whitespace between
# tokens is dropped and the spacing after `:` and `,` is made this script's own; nothing
# else is interpreted, nothing is repaired, and no value is coerced. An unknown key, a
# changed value, a truncated file and anything outside the fifteen keys the writer writes
# stay exactly as damaged as they were — a lenient parser here would undo what M28.12 was
# about.
_record_as_lines() {
  # A character scanner rather than a regex: the only way to know whether a `{` or a `,`
  # is structure or is text inside a value is to know whether a string is open, and a
  # line-wise pattern cannot. Strings are copied through untouched, escapes included.
  #
  # LC_ALL=C makes that a scan of BYTES, which is what it is: every byte is copied through,
  # so a multi-byte character comes out the way it went in, and a file that is not text at
  # all — the wrong path, a log, a device — is refused below instead of making awk complain
  # about the operator's locale on its way there. The NUL goes for the same reason and only
  # that reason: JSON text has none, so this removes nothing a record could contain, and
  # what it saves the operator is a line of bash's own warning printed over a refusal.
  tr -d '\000' | LC_ALL=C awk '
    { text = text $0 "\n" }
    END {
      depth = 0; instring = 0; escaped = 0; out = ""
      total = length(text)
      for (i = 1; i <= total; i++) {
        c = substr(text, i, 1)
        if (instring) {
          out = out c
          if (escaped) { escaped = 0 }
          else if (c == "\\") { escaped = 1 }
          else if (c == "\"") { instring = 0 }
          continue
        }
        if (c == "\"") { instring = 1; out = out c; continue }
        if (c == " " || c == "\t" || c == "\n" || c == "\r") { continue }
        if (c == "{" || c == "[") {
          depth++
          out = out c
          if (depth == 1) { out = out "\n  " }
          continue
        }
        if (c == "}" || c == "]") {
          depth--
          if (depth == 0) { out = out "\n" c } else { out = out c }
          continue
        }
        if (c == ":") { out = out ": "; continue }
        if (c == ",") {
          if (depth == 1) { out = out ",\n  " } else { out = out ", " }
          continue
        }
        out = out c
      }
      print out
    }
  '
}

# --- the extractors -----------------------------------------------------------------------
#
# EVERY ONE OF THEM TAKES THE TEXT AS A HERESTRING, never `printf … | `, and that is a
# correctness rule rather than a style (found in review, M28.15 round 1). Under `pipefail`
# a `printf "%s\n" "${RECORD}" | grep -q …` pipeline returns 141 whenever grep matches
# early and exits while printf still has bytes to write — which happens once the text is
# larger than a pipe buffer. Measured on an unchanged, perfectly legal 64 KB record: six
# refusals in twelve consecutive `status` runs, each naming a DIFFERENT valid key, because
# `has_key` read 141 as "that key is not there". One host, one file, one minute, two
# verdicts — the exact thing this milestone exists to stop, arriving through a pipe. A
# herestring is written by the shell itself, so there is no writer to kill.
#
# The same trap has a second half, and M28.18 closed it here: `… <<<"${RECORD}" | head -n 1`
# puts an EARLY-EXITING READER on the other end of a pipe whose producer is the one holding
# the record, so a record with enough matching lines kills the `sed` instead of the
# `printf`. `_record_first_line` takes the first line of a string already in this shell and
# opens no pipe at all.

# The first line of a string, without a pipe.
_record_first_line() {
  local first
  IFS= read -r first <<<"$1" || true
  printf '%s' "${first}"
}

# One field of the record — one key per line, so this is a line-wise read and still needs no
# JSON parser. The value with its quotes off.
#
# WHAT IT DOES NOT READ, and this is why it is not derived from `_record_raw_field`: the
# capture is `[^",]*`, so a value holding a comma or a quote — `"offsite": "ye,s"` — does
# not match the pattern at all and comes back EMPTY, although the validator passed it (a
# quoted string under LONGEST_VALUE is all that check asks of it). The writer sanitises
# every value it writes to [A-Za-z0-9_+:/.-], so only a hand edit can produce one, and an
# empty answer sends `status` to its "the record says …" branch and the panel to
# Destination.UNKNOWN — the same standing on both channels. Kept exactly as it was
# through M28.18 for that reason: unifying the two extractors would give those records a
# different sentence on one channel only, which is the drift this library exists to stop.
_record_field() {
  _record_first_line "$(
    sed -n "s/^[[:space:]]*\"$1\": *\"\{0,1\}\([^\",]*\)\"\{0,1\},\{0,1\}$/\1/p" \
      <<<"${RECORD}"
  )"
}

# The raw text after `"key":`, trailing comma removed. Empty when the key is absent — the
# two are told apart with `_record_has_key`, because "no such key" and "an empty value" are
# different faults and only one of them is this reader's business.
_record_raw_field() {
  local raw
  raw="$(_record_first_line "$(
    sed -n "s/^[[:space:]]*\"$1\"[[:space:]]*://p" <<<"${RECORD}"
  )")"
  printf '%s' "${raw}" \
    | tr -d '\r' \
    | sed -e 's/^[[:space:]]*//' -e 's/,[[:space:]]*$//' -e 's/[[:space:]]*$//'
}

_record_has_key() {
  grep -q "^[[:space:]]*\"$1\"[[:space:]]*:" <<<"${RECORD}"
}

_record_missed_dates() {
  grep '"missed_dates"' <<<"${RECORD}" \
    | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}' || true
}

# The numbers that come back OUT of the record and then go into arithmetic. `$(( ))` reads a
# leading zero as octal and dies on `08`, so anything that has been on a disk — where a hand
# edit, a half-written file or a future writer can put one — is forced to base 10 before it
# is counted with. The same trap as HASHI_BACKUP_AT's hour, one file over.
_record_number() {
  local raw="${1//[^0-9]/}"
  [ -n "${raw}" ] || { printf '0'; return; }
  printf '%s' "$((10#${raw}))"
}

# --- the strict validator -----------------------------------------------------------------
#
# WHY THIS EXISTS AT ALL, because `status` used to have none of it and that was the finding
# (M28.12). A record with `schema: 99`, or a thousand-character `outcome`, or a
# `last_success` that is not a run, was printed VERBATIM as fact — "last success: never,
# last attempt: never", a confident schedule line, exit 0 — which is byte-for-byte what a
# machine that has simply never taken a backup prints. Meanwhile the panel, reading the same
# file, called it unreadable and assumed nothing from it, and then sent the operator here to
# find out more. The two channels have to agree about a damaged file or the weaker one
# teaches the operator to disbelieve the other.
#
# The rules are control/app/services/backups.py's, deliberately, key for key: an unknown
# `schema`, a missing key it reads, a timestamp that is not one, a number that is not one, a
# missed date that is not a date, a nested entry that is not a run, or any string over
# LONGEST_VALUE. And deliberately NOT unreadable, in both readers: an `outcome` this version
# has no meaning for (it is named verbatim instead), an `offsite` word it does not know (it
# collapses into neither answer), and A KEY NEITHER OF THEM KNOWS — `_parse` ignores unknown
# keys by documented design, so that a later version of the writer adding a sixteenth key
# cannot make this panel go unreadable, and teaching the shell to refuse them would
# manufacture the very disagreement this library exists to close. The closed key set is
# enforced on the WRITER, by tests/infra/test_backup_schedule.py::RECORD_KEYS.

# One `"key": "value"` string, or a reason it is not one. Everything the panel's ``_text``
# refuses is refused here: a missing key, and a value longer than it reads.
_record_string_problem() {
  local raw
  _record_has_key "$1" || { printf '%s' "$1"; return 0; }
  raw="$(_record_raw_field "$1")"
  case "${raw}" in
    '"'*'"') ;;
    *) printf '%s' "$1"; return 0 ;;
  esac
  raw="${raw#\"}"; raw="${raw%\"}"
  [ "${#raw}" -le "${LONGEST_VALUE}" ] || printf '%s' "$1"
}

# One of the three nested entries: `null`, or a run with a timestamp, a whole exit code
# and an outcome. `null` and a run are both statements the record is entitled to make;
# "this line is not a run" is not, and it becomes the same refusal as a broken schema
# rather than being reported as a host that has never had a successful backup.
#
# It reads the entry off ONE line and still does, which until M28.15 meant a record whose
# nested entries had been pretty-printed over four lines was reported damaged while the
# panel read it happily. That is `_record_as_lines`'s job now, above, and none of the checks
# here were loosened to do it: what arrives here is the same bytes with the whitespace
# between them made this library's own.
_record_entry_problem() {
  local raw at code outcome
  _record_has_key "$1" || { printf '%s' "$1"; return 0; }
  raw="$(_record_raw_field "$1")"
  [ "${raw}" = "null" ] && return 0
  case "${raw}" in
    '{'*'}') ;;
    *) printf '%s' "$1"; return 0 ;;
  esac
  case "${raw}" in *'"outcome":'*) ;; *) printf '%s' "$1"; return 0 ;; esac
  at="$(printf '%s' "${raw}" | sed -n 's/.*"at": *"\([^"]*\)".*/\1/p')"
  code="$(printf '%s' "${raw}" | sed -n 's/.*"exit_code": *\(-\{0,1\}[0-9]\{1,9\}\).*/\1/p')"
  outcome="$(printf '%s' "${raw}" | sed -n 's/.*"outcome": *"\([^"]*\)".*/\1/p')"
  [[ "${at}" =~ ${A_TIMESTAMP} ]] || { printf '%s' "$1"; return 0; }
  [ -n "${code}" ] || { printf '%s' "$1"; return 0; }
  [ "${#outcome}" -le "${LONGEST_VALUE}" ] || printf '%s' "$1"
}

# Which key makes this file unreadable, or nothing at all. A KEY NAME and never a value: the
# reason an operator needs is which field is wrong, and printing the field's contents back
# at them is how a record starts being a place things leak from.
_record_problem() {
  local raw problem key day
  raw="$(_record_raw_field schema)"
  [ "${raw}" = "${RECORD_SCHEMA}" ] || { printf 'schema'; return 0; }

  for key in at at_source zone zone_source offsite; do
    problem="$(_record_string_problem "${key}")"
    [ -z "${problem}" ] || { printf '%s' "${problem}"; return 0; }
  done

  for key in last_attempt last_success last_failure; do
    problem="$(_record_entry_problem "${key}")"
    [ -z "${problem}" ] || { printf '%s' "${problem}"; return 0; }
  done

  _record_has_key missed_total || { printf 'missed_total'; return 0; }
  raw="$(_record_raw_field missed_total)"
  [[ "${raw}" =~ ^[0-9]{1,9}$ ]] || { printf 'missed_total'; return 0; }

  _record_has_key missed_dates || { printf 'missed_dates'; return 0; }
  raw="$(_record_raw_field missed_dates)"
  case "${raw}" in
    '['*']') ;;
    *) printf 'missed_dates'; return 0 ;;
  esac
  raw="${raw#[}"; raw="${raw%]}"
  for day in $(printf '%s' "${raw}" | tr -d '"' | tr ',' ' '); do
    [[ "${day}" =~ ${A_DATE} ]] || { printf 'missed_dates'; return 0; }
  done
}

# --- the reading --------------------------------------------------------------------------

# Everything the caller is allowed to believe, taken out of the text that has just passed
# the validator above. In the SAME pass on purpose: a capture that could be reached without
# the validation having run is the lenient reader coming back.
_record_capture() {
  READING_DUE_DATE="$(_record_field due_date)"
  READING_ATTEMPTS="$(_record_number "$(_record_field attempts)")"
  READING_RETRY_AT="$(_record_field retry_not_before)"
  READING_OFFSITE="$(_record_field offsite)"
  READING_MISSED_DATES="$(_record_missed_dates | tr '\n' ' ')"
  READING_MISSED_TOTAL="$(_record_number "$(_record_field missed_total)")"
  # The three nested objects, read off their single lines.
  local line
  for line in last_attempt last_success last_failure; do
    local raw at due code outcome
    raw="$(_record_first_line "$(
      sed -n "s/^[[:space:]]*\"${line}\": \(.*\),\{0,1\}$/\1/p" <<<"${RECORD}"
    )")"
    [ -n "${raw}" ] && [ "${raw}" != "null," ] && [ "${raw}" != "null" ] || continue
    at="$(printf '%s' "${raw}" | sed -n 's/.*"at": "\([^"]*\)".*/\1/p')"
    due="$(printf '%s' "${raw}" | sed -n 's/.*"due_date": "\([^"]*\)".*/\1/p')"
    code="$(printf '%s' "${raw}" | sed -n 's/.*"exit_code": \([0-9]*\).*/\1/p')"
    outcome="$(printf '%s' "${raw}" | sed -n 's/.*"outcome": "\([^"]*\)".*/\1/p')"
    case "${line}" in
      last_attempt) READING_LAST_AT="${at}"; READING_LAST_DUE="${due}"
                    READING_LAST_CODE="$(_record_number "${code}")"
                    READING_LAST_OUTCOME="${outcome}" ;;
      last_success) READING_OK_AT="${at}"; READING_OK_DUE="${due}"
                    READING_OK_CODE="$(_record_number "${code}")"
                    READING_OK_OUTCOME="${outcome}" ;;
      last_failure) READING_BAD_AT="${at}"; READING_BAD_DUE="${due}"
                    READING_BAD_CODE="$(_record_number "${code}")"
                    READING_BAD_OUTCOME="${outcome}" ;;
    esac
  done
}
