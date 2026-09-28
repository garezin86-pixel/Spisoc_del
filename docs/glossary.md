# Словарь терминов

В коде, БД и API только английские названия, в интерфейсе только русские из этой таблицы.

| Термин (код) | Русский в UI | Таблица | API |
|---|---|---|---|
| Client | Клиент | `clients` | `/clients` |
| Contact | Контакт | `contacts` | `/clients/{id}/contacts` |
| Interaction | Взаимодействие (заметка, звонок, встреча) | `interactions` | `/clients/{id}/interactions` |
| Deal | Сделка | `deals` | `/deals` |
| Pipeline | Воронка | `pipelines` | `/pipelines` |
| Stage | Стадия | `stages` | `/pipelines/{id}/stages` |
| Activity feed | Лента активности | нет (строится из аудита) | `/analytics/activity` (существует) |

Правило: слово Activity в коде относится только к существующей ленте аудита, для CRM-записей используется Interaction.
