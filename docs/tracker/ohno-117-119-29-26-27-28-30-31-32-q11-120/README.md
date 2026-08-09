# ohno-117-119-29-26-27-28-30-31-32-q11-120

**Type:** feature (epic execution — семь задач подряд)
**Goal:** выполнить остаток эпика #117 — пункты бэклога 26–32, разложенные в
задаче #119 (`docs/tracker/ohno-117-epic-119/`), в порядке диспатча владельца
**29 → 26 → 27 → 28 → 30 → 31 → 32**. По вопросу Q11 (какой именно второй формат
подписки) владелец подтвердил вариант **(b)** — delivery-эндпоинт отдаёт
per-client конфиг-файлы за тем же токеном.

**Baseline ревью:** `7b12358` (`git rev-parse HEAD` на старте).

**Одна задача = один прогон = одна зона.** Каждая закрывается прогоном
review-loop с независимым `reviewer-strict`.

| Пункт | id | Зона | Файл задачи |
|---|---|---|---|
| 29 | `control-criteria-2-and-3-from-the-panel` | `control` | `tasks/29-control-criteria-2-and-3.md` |
| 26 | `edge-subscription-serialization-contract` | `edge` | `tasks/26-edge-serialization-contract.md` |
| 27 | `control-second-subscription-format` | `control` | `tasks/27-control-second-format.md` |
| 28 | `edge-transport-wireguard` | `edge` | `tasks/28-edge-transport-wireguard.md` |
| 30 | `edge-criterion-4-a-brand-new-transport-package` | `edge` | `tasks/30-edge-criterion-4.md` |
| 31 | `infra-panel-bootstrap` | `infra` | `tasks/31-infra-panel-bootstrap.md` |
| 32 | `infra-restore-proves-the-backup` | `infra` | `tasks/32-infra-restore-proves-backup.md` |

Текст приёмки по каждому пункту заморожен в
`docs/tracker/ohno-117-epic-119/tasks/epic-decomposition-ohno-117-epic-119.md` §2
— этот каталог его не переписывает, а исполняет.
