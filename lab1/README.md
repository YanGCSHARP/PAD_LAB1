# Лабораторная работа №1. RAG-система по Dota 2

Вопросно-ответная система на основе Retrieval-Augmented Generation: отвечает на
вопросы о героях, предметах, механиках и патчах Dota 2 **только по собранной базе
знаний** и указывает источники. Если ответа в базе нет — честно сообщает об этом.

- **Источники:** официальный сайт dota2.com (русский) и Dota 2 Wiki на Fandom (английский).
- **Вопросы:** на русском (кросс-язычный поиск по смешанному корпусу).
- **Стек:** Python (pipeline, эксперименты) + Blazor WebAssembly (.NET 10, интерфейс) + Qdrant (Docker) + Groq / Gemini API.

Результаты экспериментов и выводы — в [experiments/REPORT.md](experiments/REPORT.md).

---

## Архитектура

```
                 dota2.com /datafeed (JSON, RU)      dota2.fandom.com (MediaWiki API, EN)
                              │                                   │
                              ▼                                   ▼
 ┌──────────────── Grabber (src/grabber) ────────────────────────────────────────┐
 │ листинг → проверка версии (revid / номер патча) → скачивание → raw JSON/HTML  │
 │ → парсер → Document(sections, metadata) → сравнение SHA-256 → сохранение      │
 │ манифест SQLite: new / updated / unchanged / skipped / duplicate / removed    │
 └──────────────────────────────┬────────────────────────────────────────────────┘
                                ▼
 ┌──────────── Preprocessing (src/preprocessing) ────────────┐
 │ очистка HTML и вики-мусора → нормализация Unicode →       │
 │ chunking: fixed / fixed+overlap / paragraph / section     │
 │ + metadata: source, url, title, section, doc_id, lang,    │
 │   entity_type, updated_at                                 │
 └──────────────────────────────┬────────────────────────────┘
                                ▼
      Embeddings (src/embeddings, HF transformers, кэш векторов в SQLite)
                                ▼
      Vector Store: Qdrant (Docker), коллекция на каждую конфигурацию
                                │
          User Query ───────────┤
                                ▼
      Retriever (src/retrieval): dense / BM25 / hybrid (RRF), фильтр по metadata
                                ▼  Top-K кандидатов
      Filters (src/filtering): порог cosine, мин. длина, дедупликация, лимит на документ
                                ▼
      Reranker (src/reranking): cross-encoder → Top-N, порог релевантности («ворота» отказа)
                                ▼
      LLM (src/generation): системный промпт + контекст [1..N] + вопрос → Groq / Gemini
                                ▼
      Ответ со ссылками [n] + список источников  ──►  FastAPI (src/api) ──► Blazor UI
```

### Структура репозитория

```
lab1/
├── README.md                 — этот файл
├── requirements.txt          — зависимости Python
├── docker-compose.yml        — Qdrant
├── configs/default.yaml      — все параметры pipeline'а
├── src/
│   ├── grabber/              — источники, HTTP-клиент с повторами, манифест
│   ├── preprocessing/        — очистка, нормализация, 4 стратегии chunking
│   ├── embeddings/           — 4 embedding-модели, кэш векторов
│   ├── retrieval/            — Qdrant, BM25, RRF
│   ├── filtering/            — фильтры контекста
│   ├── reranking/            — cross-encoder'ы
│   ├── generation/           — промпты, клиент LLM с кэшем, источники
│   ├── evaluation/           — датасет, метрики, LLM-as-a-Judge
│   ├── api/                  — FastAPI (+ раздача UI)
│   ├── hf.py                 — bi-/cross-encoder на transformers
│   ├── pipeline.py           — сборка RAG pipeline
│   └── cli.py                — команды grab / stats / index / ask
├── ui/RagLab.Web/            — Blazor WebAssembly (C#)
├── data/                     — документы, манифест, кэши (пересобираются), eval/questions.jsonl
├── experiments/              — скрипты экспериментов, results/*.csv, figures/*.png, REPORT.md
└── tests/                    — pytest
```

---

## Запуск

Требования: Python 3.12+ (проверено на 3.14), Docker Desktop, .NET SDK 10 (только для сборки UI).

```bash
cd lab1
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Ключи API — в `.env` (в `lab1/` или в корне репозитория), формат в [.env.example](.env.example).
Бесплатные ключи: [Groq](https://console.groq.com/keys), [Google AI Studio](https://aistudio.google.com/apikey).

```bash
python -m src.cli check                # ключи найдены?
docker compose up -d                   # Qdrant на http://localhost:6333

python -m src.cli grab                 # сбор документов (~8 мин первый раз, далее — только изменения)
python -m src.cli stats                # статистика корпуса
python -m src.cli index                # chunks + эмбеддинги + коллекция Qdrant
python -m src.cli ask "Чем Silence отличается от Break?" --show-context
```

Веб-интерфейс:

```bash
dotnet publish ui/RagLab.Web -c Release -o ui/dist     # один раз после изменений UI
python -m uvicorn src.api.app:app --port 8000          # API + UI → http://localhost:8000
```

Эксперименты и тесты:

```bash
python experiments/prebuild.py grid          # заранее построить индексы сетки chunking (долго на CPU)
python experiments/run_retrieval.py          # этапы S1–S7 (без LLM)
python experiments/run_generation.py         # LLM × промпт + судья
python experiments/make_figures.py           # графики в experiments/figures
python -m pytest tests
```

Повторный запуск `grab` не скачивает неизменённое: страницы Fandom сверяются по
`revid`, патчи — по номеру, остальное — по SHA-256 содержимого.
`grab --reparse` пересобирает документы из сохранённых сырых ответов (после правки
парсера — без нагрузки на источники).

---

## Ключевые решения

| Компонент | Выбор | Почему | Альтернативы |
|---|---|---|---|
| Источники | dota2.com `/datafeed` + Fandom MediaWiki API | официальный сайт рендерится JS, но данные приходят из JSON API — стабильно и структурировано; Fandom даёт механики и подробности | Liquipedia (киберспорт, лимит 1 запрос/2 с, `parse` — 1/30 с), парсинг HTML в headless-браузере |
| Инкрементальность | `revid` / номер патча / SHA-256 + манифест SQLite | дешёвая проверка без скачивания, где источник это позволяет; иначе — по содержимому | ETag (dota2.com отдаёт только `Last-Modified`, который меняется при каждом запросе) |
| Chunking | см. эксперимент S1–S3 | | fixed, overlap, paragraph, section |
| Токенизация | токенизатор XLM-R | общий у всех трёх семейств embedding-моделей → chunk точно влезает в модель | символы / слова |
| Embeddings | см. S4 | корпус RU+EN, вопросы RU → нужны мультиязычные модели | e5-small/base, MiniLM, bge-m3 |
| Vector DB | Qdrant (Docker) | фильтрация по payload (metadata) прямо в запросе, коллекция на конфигурацию, веб-панель, тот же API в проде | FAISS (нет metadata-фильтров), Chroma |
| Reranker | см. S6 | cross-encoder видит вопрос и chunk вместе | mMiniLM (быстрый), bge-reranker-v2-m3 (точный) |
| LLM | Groq: gpt-oss-120b, qwen3.8-27b (open-weight) | бесплатно, быстро, open-weight модели; ноутбук без GPU | локальный Ollama (медленно на CPU) |
| Судья | Gemini Flash | другое семейство → меньше «самооценки» | та же модель, что генерирует |

### Защита от галлюцинаций

1. **Строгий промпт:** только контекст, ссылка `[n]` после каждого утверждения, фиксированная фраза отказа.
2. **«Ворота» отказа:** если после reranker'а ни один chunk не набрал порог релевантности, LLM не вызывается — система сразу отвечает «недостаточно информации» (порог выбран в эксперименте S7).
3. **Источники:** в ответе — только реально процитированные фрагменты (ссылки и URL).

### Особенности окружения (Windows)

На ноутбуке включён **Smart App Control**: он блокирует неподписанные нативные DLL и
локально собранные .NET-сборки. Поэтому:
- эмбеддинги и reranker написаны на `transformers` напрямую (без `sentence-transformers` → `scikit-learn`);
- LLM вызываются через `requests` (без SDK `openai` → `jiter`);
- Qdrant запущен в Docker (embedded-режим требует `pywin32`);
- UI — Blazor **WebAssembly**: .NET-код выполняется в браузере, а собранные статические файлы раздаёт FastAPI.
