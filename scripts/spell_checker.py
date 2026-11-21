#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spell_checker.py — орфографический чек + словарь для русского текста (pymorphy3).

Движок: pymorphy3 (MorphAnalyzer). Слово, которого нет в словаре pymorphy3,
делится на 4 категории:

  1. [ЗАЙМСТВ. OK]  — устоявшееся заимствованное слово (whitelist из
     assets/vocabulary.json). Оставляем как есть.
  2. [СЛОП-СЛОВО]     — ИИ-неологизм / «вода» (из assets/vocabulary.json).
     Показываем русские альтернативы. Текст НЕ меняется автоматически,
     чтобы агент выбрал тот вариант, что уместен в контексте.
  3. [ОПЧАТА]        — настоящая опечатка: hunspell нашёл близкое слово
     и pymorphy3 подтвердил, что это валидное слово. При --correct
     подставляется.
  4. [НЕЯСНО]        — слово неизвестно ни pymorphy3, ни словарю.
     Показываем подсказку hunspell (если есть), но решение оставляет агенту.

Использование:
    python3 spell_checker.py <файл>
    python3 spell_checker.py <файл> --correct            # выводит чистый текст (только опечатки)
    python3 spell_checker.py <файл> --correct --out fixed.txt
    python3 spell_checker.py <файл> --json               # машино-читаемый вывод
    echo "текст" | python3 spell_checker.py -            # stdin
    echo "текст" | python3 spell_checker.py - --correct

Данные: assets/vocabulary.json (accepted_loanwords + slop). Расширяйте сами.
"""

from __future__ import annotations

import os
import re
import sys
import json
import gzip
import shutil
import tempfile
import subprocess

# --- цветовой вывод (colorama опционально) -----------------------------------
try:
    from colorama import Fore, Style, init
    init(autoreset=True)
    HAS_COLOR = True
except Exception:
    Fore = Style = None
    def init(*a, **kw):
        pass
    HAS_COLOR = False

def RST():
    return Style.RESET_ALL if HAS_COLOR else ""
def CRED():
    return Fore.RED if HAS_COLOR else ""
def CYAN():
    return Fore.CYAN if HAS_COLOR else ""
def GREEN():
    return Fore.GREEN if HAS_COLOR else ""
def YELLOW():
    return Fore.YELLOW if HAS_COLOR else ""
def BOLD():
    return Style.BOLD if HAS_COLOR else ""

# --- константы ----------------------------------------------------------------
# Регулярка: русские слова (кириллица + ё). Не ловим латиницу/цифры.
WORD_RE = re.compile(r"[А-Яа-яЁё]+")
# Сколько вариантов подсказки показывать по умолчанию.
DEFAULT_SUGGESTS = 3
# Допустимая длина суффикса заимствованного слова при префикс-совпадении.
MAX_EXTRA = 5
SYSTEM_HUNSPELL_DIRS = ["/usr/share/hunspell", "/usr/share/dicts"]


def skill_dir() -> str:
    """Каталог навыка (каталог, где лежит SKILL.md). 2 уровня вверх от .py."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_morph():
    try:
        import pymorphy3
        return pymorphy3.MorphAnalyzer()
    except ImportError:
        sys.exit("pymorphy3 не установлен. Установите: pip install pymorphy3")


# --- поиск / подготовка Hunspell-каталога -----------------------------------
def _prepare_bundled(skill_root: str):
    assets = os.path.join(skill_root, "assets", "ru_hunspell")
    gz = os.path.join(assets, "ru_RU.dic.gz")
    plain = os.path.join(assets, "ru_RU.dic")
    aff = os.path.join(assets, "ru_RU.aff")
    if os.path.exists(plain):
        return plain
    if os.path.exists(gz):
        try:
            with open(plain, "wb") as out:
                with gzip.open(gz, "rb") as gzfile:
                    shutil.copyfileobj(gzfile, out)
        except Exception:
            cache_dir = tempfile.mkdtemp(prefix="ru_hunspell_")
            with open(os.path.join(cache_dir, "ru_RU.dic"), "wb") as out:
                with gzip.open(gz, "rb") as gzfile:
                    shutil.copyfileobj(gzfile, out)
        if os.path.exists(aff) and not os.path.exists(os.path.join(cache_dir, "ru_RU.aff")):
            shutil.copy(aff, os.path.join(cache_dir, "ru_RU.aff"))
        return plain if os.path.exists(plain) else os.path.join(cache_dir, "ru_RU.dic")
    return None


def find_hunspell_dic(skill_root: str, override=None):
    """Путь к готовому ru_RU.dic (или None)."""
    candidates = []
    if override:
        candidates.append(override)
    bundled = _prepare_bundled(skill_root)
    if bundled:
        candidates.append(bundled)
    home = os.path.expanduser("~")
    for d in [
        os.path.join(home, ".local", "share", "TelegramDesktop",
                     "tdata", "dictionaries", "ru_RU"),
    ] + SYSTEM_HUNSPELL_DIRS:
        if not os.path.isdir(d):
            continue
        for name in ("ru_RU.dic", "ru-ru.dic"):
            p = os.path.join(d, name)
            if os.path.exists(p):
                candidates.append(p)
    for dic in candidates:
        if os.path.exists(dic):
            return dic
    return None


def hunspell_bin():
    for p in ("/usr/sbin/hunspell",):
        if os.path.exists(p):
            return p
    return shutil.which("hunspell") or ""


def get_suggestions(word: str, dic_path: str, n: int = DEFAULT_SUGGESTS):
    """Подсказки от hunspell для word. Hunspell: -d <имя_без_.dic> + cwd=каталог."""
    if not dic_path or not os.path.exists(dic_path):
        return []
    h = hunspell_bin()
    if not h:
        return []
    base = os.path.basename(dic_path)
    if base.endswith(".dic"):
        base = base[:-4]
    cwd = os.path.dirname(os.path.abspath(dic_path))
    try:
        p = subprocess.run(
            [h, "-d", base, "-i", "UTF-8"],
            input=word + "\n", capture_output=True, text=True, timeout=30, cwd=cwd,
        )
    except Exception:
        return []
    line = ""
    for l in p.stdout.strip().splitlines():
        l = l.strip()
        if l.startswith("&"):
            line = l
            break
    if not line:
        return []
    parts = line.split(": ", 1)
    if len(parts) < 2:
        return []
    sugg = [s.strip() for s in parts[1].split(",")]
    sugg = [s for s in sugg if s]
    return sugg[:n]


# --- словарь (accepted + slop) ----------------------------------------------
def _load_vocab(skill_root: str):
    path = os.path.join(skill_root, "assets", "vocabulary.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _prefix_match(word: str, lemmas: list) -> bool:
    """word == lemma или word начинается с lemma (с ограничением на длину суффикса)."""
    wl = len(word)
    for lem in lemmas:
        if word == lem:
            return True
        if wl <= len(lem) + MAX_EXTRA and word.startswith(lem):
            return True
    return False

def _is_accepted(word: str, vocab: dict) -> bool:
    return _prefix_match(word, vocab.get("accepted_loanwords", []))

def _slop_match(word: str, vocab: dict):
    """Возвращает список альтернатив, если word — слоп-слово, иначе None."""
    slop = vocab.get("slop", {})
    wl = len(word)
    for lem, alts in slop.items():
        if word == lem:
            return alts
        if wl <= len(lem) + MAX_EXTRA and word.startswith(lem):
            return alts
    return None

def _categorize(lw: str, vocab: dict, morph, dic_path: str, n: int):
    """Классифицирует неизвестное слово. Возвращает (cat, alts, suggestion, verified)."""
    if _is_accepted(lw, vocab):
        return "accepted", None, None, False
    alts = _slop_match(lw, vocab)
    if alts:
        return "slop", alts, None, False
    sugg = get_suggestions(lw, dic_path, n=n)
    top = sugg[0] if sugg else None
    if top:
        verified = morph.word_is_known(top, strict=False)
        if verified:
            return "typo", None, top, True
        return "unclear", None, top, False
    return "unclear", None, None, False


# --- ядро --------------------------------------------------------------------
def _context(text: str, m):
    start = max(0, m.start() - 45)
    end = min(len(text), m.end() + 45)
    return text[start:end]

def _match_case(orig: str, fix: str) -> str:
    """Сохраняем регистр: если orig начиналось с заглавной — и fix."""
    if orig and orig[0].isupper():
        return fix.capitalize()
    return fix


def check(text: str, morph, dic_path: str, n_suggests: int = DEFAULT_SUGGESTS,
          vocab: dict | None = None):
    """Проверяет text. Возвращает dict с items, corrected и stats."""
    if vocab is None:
        vocab = _load_vocab(skill_dir())

    items = []
    corrected_parts = []
    last = 0
    counts = {"typo": 0, "slop": 0, "accepted": 0, "unclear": 0}

    for m in WORD_RE.finditer(text):
        word = m.group(0)
        lw = word.lower()
        if morph.word_is_known(word, strict=False):
            corrected_parts.append(text[last:m.end()])
            last = m.end()
            continue

        prefix = text[:m.start()]
        line_no = prefix.count("\n") + 1
        offset = m.start()
        cat, alts, suggestion, verified = _categorize(lw, vocab, morph, dic_path, n_suggests)
        counts[cat] += 1
        items.append({
            "original": word,
            "category": cat,
            "suggestion": suggestion,
            "alternatives": alts,
            "verified": verified,
            "line_no": line_no,
            "offset": offset,
            "context": _context(text, m),
        })
        if cat == "typo" and suggestion:
            corrected_parts.append(text[last:m.start()])
            corrected_parts.append(_match_case(word, suggestion))
        else:
            corrected_parts.append(text[last:m.end()])
        last = m.end()

    if last < len(text):
        corrected_parts.append(text[last:])
    corrected = "".join(corrected_parts)

    stats = {
        "words": len(WORD_RE.findall(text)),
        "unknown": len(items),
        "typo": counts["typo"],
        "slop": counts["slop"],
        "accepted": counts["accepted"],
        "unclear": counts["unclear"],
    }
    return {
        "ok": (counts["typo"] == 0 and counts["slop"] == 0),
        "items": items,
        "corrected": corrected,
        "stats": stats,
    }


# --- отчёт --------------------------------------------------------------------
def _cat_label(cat):
    return {
        "typo": "[ОПЧАТА]",
        "slop": "[СЛОП-СЛОВО]",
        "accepted": "[ЗАЙМСТВ. OK]",
        "unclear": "[НЕЯСНО]",
    }.get(cat, "[?]")

def print_report(res: dict, show_corrected: bool):
    st = res["stats"]
    print(CYAN() + BOLD() + "— Орфографическая проверка (pymorphy3 + Hunspell + словарь) " + RST())
    print(f"Слов: {st['words']}\n")
    if res["ok"]:
        print(GREEN() + "✅ Текст чистый: опечаток и «воды» не найдено." + RST())
    else:
        print(f"Итог — опечатки: {st['typo']}, слоп-слова: {st['slop']}, "
              f"заимствования (OK): {st['accepted']}, неясных: {st['unclear']}.\n")
    for i, it in enumerate(res["items"], 1):
        cat = it["category"]
        line = f"{it['original']!r}  {_cat_label(cat)}"
        if cat == "typo":
            v = " [OK]" if it["verified"] else " [review]"
            line += f"  →  {it['suggestion']}{v}"
        elif cat == "slop":
            line += "  → альтернативы: " + " / ".join(it["alternatives"][:5])
        elif cat == "accepted":
            line += "  (устоявшееся заимствование — оставляем)"
        elif cat == "unclear":
            if it["suggestion"]:
                line += f"  (hunspell: {it['suggestion']}{ ' (вериф)' if it['verified'] else ''} — проверьте вручную)"
            else:
                line += "  (неизвестное слово — проверьте вручную)"
        print(CYAN() + f"{i}." + RST() + "  " + line)
        print(f"     строка {it['line_no']}, см. {it['offset']}, контекст: …{it['context'].strip()}…")
    if show_corrected:
        print(CYAN() + "\n— Исправленный текст (заменены только верифицированные опечатки) —" + RST())
        print(res["corrected"])


def main():
    import argparse
    ap = argparse.ArgumentParser(description="pymorphy3 орфографический чек русский текст")
    ap.add_argument("file", nargs="?", default="-", help="путь к файлу или '-' (stdin)")
    ap.add_argument("--correct", action="store_true", help="выводить исправленный текст")
    ap.add_argument("--out", help="сохранить исправленный текст в файл")
    ap.add_argument("--json", action="store_true", help="машино-читаемый вывод")
    ap.add_argument("--suggests", type=int, default=DEFAULT_SUGGESTS, help="число подсказок (default=3)")
    ap.add_argument("--dict-dir", help="каталог с ru_RU.dic (переопределяет поиск)")
    args = ap.parse_args()

    if args.file == "-":
        text = sys.stdin.read()
    else:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            sys.exit(f"Не удалось открыть файл: {e}")

    if not text.strip():
        if args.json:
            print(json.dumps({"ok": True, "items": [], "corrected": "",
                              "stats": {"words": 0, "unknown": 0, "typo": 0,
                                        "slop": 0, "accepted": 0, "unclear": 0}}))
        else:
            print("Текст пуст.")
        return

    morph = load_morph()
    skill_root = skill_dir()
    dic_path = find_hunspell_dic(skill_root, getattr(args, "dict_dir", None))
    res = check(text, morph, dic_path, n_suggests=args.suggests)

    if args.json:
        out = {
            "ok": res["ok"],
            "items": res["items"],
            "corrected": res["corrected"],
            "stats": res["stats"],
        }
        print(json.dumps(out, ensure_ascii=False))
        return

    print_report(res, show_corrected=args.correct)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(res["corrected"])
        print(CYAN() + f"\nИсправленный текст сохранён в: {args.out}" + RST())


if __name__ == "__main__":
    main()
