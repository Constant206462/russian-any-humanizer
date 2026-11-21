# Russian Humanizer / Очеловечивание русского текста
*Основано на https://github.com/Horosheff/russian-humanizer, v1.0.0, от @horosheff.*

Русскоязычный навык-редактор: находит и убивает «воду», канцелярит и
нейросетевые штампы (AI slop) в русском тексте, проверяет и чинит орфографию
на pymorphy3.

## Что умеет
- **Обнаружение штампов + правила переработки** — ловит клише во всех падежах и
  подсказывает живые замены.
- **Орфографический чек** (`scripts/spell_checker.py`) — находит и чинит
  опечатки. Движок — `pymorphy3` (полный морфологический словарь: нет ложных
  срабатываний на спряженные глаголы и имена); подсказки — Hunspell (современный
  словарь Goudron, `assets/ru_hunspell`); каждое исправление перепроверяется
  pymorphy3 до применения.
- **Обнаружение «Правила трёх» + метрики ритма** — ловит паттерны ChatGPT
  («быстрый, надёжный и безопасный») и дисперсию длины предложений.
- **Системный запрос** — `anti_slop_prompt.md`: вставьте в свой System Prompt /
  Custom Instructions, и LLM будет писать плотный живой русский с первого раза.

## Зависимости

- `pymorphy3` — движок орфографической проверки. Установка:
  `pip install pymorphy3` (проверка: `pip show pymorphy3`).
- `hunspell` — бинарник для подсказок и обнаружения опечаток. Словарь Goudron
  встроен в `assets/ru_hunspell`; сам бинарник ставится отдельно — Debian/Ubuntu:
  `apt install hunspell`, macOS: `brew install hunspell`. Без него проверка
  работает, но без подсказок.
- `colorama` — опционально (цветной вывод в терминале).

## Как пользоваться (Hermes)
Запускайте скрипты напрямую:

```bash
# Аудит на «воду» (Slop Score + список клише)
python3 {skill_dir}/scripts/slop_detector.py <текст.txt>

# Орфографический чек
python3 {skill_dir}/scripts/spell_checker.py <текст.txt>
python3 {skill_dir}/scripts/spell_checker.py <текст.txt> --correct         # чистый текст
python3 {skill_dir}/scripts/spell_checker.py <текст.txt> --correct --out fixed.txt
python3 {skill_dir}/scripts/spell_checker.py <текст.txt> --json           # для машинного чтения
```

## Структура
- `SKILL.md` — инструкции для агента.
- `scripts/slop_detector.py` — аудит на «воду».
- `scripts/spell_checker.py` — орфографический чек (pymorphy3 + Hunspell).
- `references/phrases.md`, `structures.md`, `examples.md` — правила и примеры.
- `anti_slop_prompt.md` — системный запрос для LLM.
- `assets/ru_hunspell/` — встроенный русский словарь Hunspell (Goudron).

---
*Сделано, чтобы русский текст снова стал живым.*
