#!/usr/bin/env bash
# WHAT: how an agent asks the project owner a BLOCKING question.
# WHY:  there is no messaging channel in this project, so this script cannot
#       fetch an answer. What it can do is stop an agent from inventing one —
#       the expensive failure is not the missing answer, it is the guess.
# HOW:  scripts/ask_owner.sh "question". Records it, then tells the caller to
#       stop and surface the question in its final report.
set -euo pipefail

question="${*:?usage: ask_owner.sh <question>}"
mkdir -p docs/tracker
printf '[%s] QUESTION: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$question" \
  >> docs/tracker/questions.log

cat <<EOF
--- OWNER INPUT REQUIRED ---
$question
----------------------------
This project has no messaging channel, so no answer will arrive here.
If you are an agent: STOP now. Put the question above in your final report and
set your status to 'blocked'. Do not guess, and do not continue past this point.
EOF
