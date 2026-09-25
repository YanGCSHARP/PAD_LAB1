# Лабораторная работа №1. RAG-система по Dota 2

Вопросно-ответная система на основе Retrieval-Augmented Generation: отвечает на
вопросы о героях, предметах, механиках и патчах Dota 2 **только по собранной базе
знаний** и указывает источники. Если ответа в базе нет — честно сообщает об этом.

- **Источники:** официальный сайт dota2.com (русский) и Dota 2 Wiki на Fandom (английский).
- **Вопросы:** на русском (кросс-язычный поиск по смешанному корпусу).
- **Стек:** Python (pipeline, эксперименты) + Blazor WebAssembly (.NET 10, интерфейс) + Qdrant (Docker) + Groq / Gemini API.

Результаты экспериментов и выводы — в [experiments/REPORT.md](experiments/REPORT.md),
отчёт в Word — [report/LR1_RAG_Dota2.docx](report/LR1_RAG_Dota2.docx).

## Результаты коротко

- **Корпус:** 765 документов (127 героев, 408 предметов и 6 патчей с dota2.com; 125 героев и 99 механик с Fandom), ≈ 4 млн символов.
- **Датасет:** 41 вопрос пяти типов, включая 7 вопросов без ответа в базе.

| | Hit@1 | Hit@5 | MRR |
|---|---|---|---|
| База: section-256, e5-small, dense | 0,500 | 0,765 | 0,635 |
| **Итог: section-128, bge-m3, hybrid, reranker bge-m3** | **0,853** | **0,941** | **0,885** |

| Генерация (судья — Gemini, 1–5) | Correctness | Faithfulness | Верные отказы |
|---|---|---|---|
| **gpt-oss-120b, строгий промпт** | **4,65** | 4,85 | **100%** |
| gpt-oss-120b, базовый промпт | 4,56 | 3,95 | 0% — модель выдумывает ответы |

Самые сильные эффекты: заголовок «Документ — Секция» в chunk'е (MRR ×1,9), reranker (+18% MRR),
строгий промпт (от 0% до 100% отказов на вопросах без ответа).

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
python experiments/run_retrieval.py          # этапы S1–S7 (без LLM); на GPU ~15 мин, на CPU — часы
python experiments/run_generation.py         # LLM × промпт + судья (~30 мин из-за лимитов API)
python experiments/run_generation.py --resummarize   # пересчитать сводку без запросов к API
python experiments/make_figures.py           # графики → experiments/figures/*.svg
python experiments/export_png.py             # SVG → PNG через браузер (http://localhost:8765)
python experiments/build_docx.py             # отчёт → report/LR1_RAG_Dota2.docx
python -m pytest tests
```

Эксперименты с поиском запускались на ПК с RTX 5060 Ti: код сам использует CUDA, если она есть
(torch ставить с `--index-url https://download.pytorch.org/whl/cu128`). Векторы кэшируются в
`data/cache/`, поэтому на ноутбуке итоговый индекс собирается из кэша за ~30 секунд.

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
| Chunking | section-128 + заголовок «Документ — Секция» | лучший MRR (S1), overlap не помог (S2), заголовок ×1,9 MRR (S3) | fixed, overlap, paragraph, 256/512 |
| Токенизация | токенизатор XLM-R | общий у всех трёх семейств embedding-моделей → chunk точно влезает в модель | символы / слова |
| Embeddings | bge-m3 | лучший MRR на RU-вопросах и устойчив к смене языка (S4) | e5-small/base, MiniLM |
| Vector DB | Qdrant (Docker) | фильтрация по payload (metadata) прямо в запросе, коллекция на конфигурацию, веб-панель, тот же API в проде | FAISS (нет metadata-фильтров), Chroma |
| Поиск | hybrid (dense + BM25, RRF), 10 кандидатов | +0,09 Hit@1 к dense (S5) | dense, BM25 |
| Reranker | bge-reranker-v2-m3, 10 → 5 | +18% MRR (S6) | без reranker, mMiniLM |
| LLM | gpt-oss-120b (Groq) + строгий промпт | лучший correctness и 100% верных отказов (раздел 4 отчёта) | qwen3.8-27b, базовый промпт, локальный Ollama (медленно на CPU) |
| Судья | Gemini 3.5 Flash-Lite | другое семейство → меньше «самооценки»; у 3.8 Flash на бесплатном тарифе слишком частые 429/503 | та же модель, что генерирует |

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
