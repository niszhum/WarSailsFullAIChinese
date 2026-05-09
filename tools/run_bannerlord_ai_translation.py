from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import requests


EXPORT_DIR_NAME = "骑砍2战帆英文文本导出"
MODULE_ID = "WarSailsFullAIChinese"
MODULE_NAME = "战帆全量AI汉化"
LANGUAGE_ID = "简体中文"

API_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/chat/completions")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
API_KEY_ENV = "DEEPSEEK_API_KEY"

GLOSSARY_COLUMNS = [
    "术语ID",
    "优先级",
    "术语类型",
    "英文术语",
    "统一中文译名",
    "分类列表",
    "模块列表",
    "出现次数",
    "来源文件示例",
    "备注",
]

DICTIONARY_COLUMNS = [
    "词条ID",
    "英文原文",
    "中文译文",
    "字符串ID列表",
    "分类列表",
    "模块列表",
    "出现次数",
    "来源文件示例",
    "记录ID示例",
    "翻译状态",
    "备注",
]

TRANSLATED_EFFECTIVE_COLUMNS = [
    "行号",
    "范围",
    "模块",
    "分类",
    "子分类",
    "来源文件",
    "XML路径",
    "记录标签",
    "记录ID",
    "字段",
    "字符串ID",
    "英文原文",
    "中文译文",
    "翻译状态",
]

PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")
MASKED_PLACEHOLDER_RE = re.compile(r"⟦P(\d+)⟧")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def append_jsonl(path: Path, item: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def load_jsonl_map(path: Path, id_key: str, value_key: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            key = str(item.get(id_key, ""))
            value = str(item.get(value_key, ""))
            if key and value:
                result[key] = value
    return result


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(text or ""))


def placeholder_safe(source: str, translation: str) -> bool:
    return placeholders(source) == placeholders(translation)


def mask_placeholders(text: str) -> tuple[str, list[str]]:
    found = PLACEHOLDER_RE.findall(text or "")
    masked = text
    for index, placeholder in enumerate(found):
        masked = masked.replace(placeholder, f"⟦P{index}⟧", 1)
    return masked, found


def unmask_placeholders(text: str, placeholder_list: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        if index < len(placeholder_list):
            return placeholder_list[index]
        return match.group(0)

    return MASKED_PLACEHOLDER_RE.sub(replace, text)


def split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split("；") if item.strip()]


def chunk_items(items: list[dict[str, str]], text_key: str, max_items: int, max_chars: int) -> Iterable[list[dict[str, str]]]:
    batch: list[dict[str, str]] = []
    chars = 0
    for item in items:
        item_chars = len(item[text_key])
        if batch and (len(batch) >= max_items or chars + item_chars > max_chars):
            yield batch
            batch = []
            chars = 0
        batch.append(item)
        chars += item_chars
    if batch:
        yield batch


def extract_json_array(raw: str) -> list[dict[str, str]]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("[")
        end = raw.rfind("]")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(raw[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("response is not a JSON array")
    normalized: list[dict[str, str]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        item_id = str(entry.get("id", "")).strip()
        translated = str(entry.get("zh", entry.get("text", entry.get("translation", "")))).strip()
        if item_id and translated:
            normalized.append({"id": item_id, "zh": translated})
    return normalized


def call_translation_api(
    api_key: str,
    system_prompt: str,
    user_payload: dict[str, object],
    timeout: int,
    retries: int,
) -> list[dict[str, str]]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0.25,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(API_URL, headers=headers, json=payload, timeout=timeout)
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(min(60, attempt * attempt * 2))
                continue
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            translations = parsed.get("translations", parsed)
            if isinstance(translations, list):
                return extract_json_array(json.dumps(translations, ensure_ascii=False))
            raise ValueError("missing translations array")
        except Exception as exc:
            last_error = exc
            time.sleep(min(60, attempt * attempt * 2))
    raise RuntimeError(f"translation API failed after {retries} retries: {last_error}")


def glossary_system_prompt() -> str:
    return (
        "你是《骑马与砍杀2：霸主》战帆资料片的中文本地化术语译者。"
        "任务是把英文术语翻成简体中文。人物、地点、家族、国家、船名、装备名全部中文化。"
        "风格为史诗叙事风，术语要短、稳定、可重复使用。"
        "不要解释，不要输出 Markdown。只输出 JSON 对象："
        "{\"translations\":[{\"id\":\"...\",\"zh\":\"...\"}]}"
    )


def dictionary_system_prompt() -> str:
    return (
        "你是《骑马与砍杀2：霸主》战帆资料片的中文本地化译者。"
        "把英文原文翻成简体中文。整体采用史诗叙事风；系统、按钮、提示保持清楚短句；对白保留角色语气。"
        "人物、地点、家族、国家、船名、装备名全部中文化。"
        "输入文本中可能有 ⟦P0⟧、⟦P1⟧ 这类占位符保护标记，必须原样保留这些标记。"
        "不要增删保护标记，不要翻译保护标记内部内容。"
        "不要解释，不要输出 Markdown。只输出 JSON 对象："
        "{\"translations\":[{\"id\":\"...\",\"zh\":\"...\"}]}"
    )


def strict_dictionary_system_prompt() -> str:
    return (
        dictionary_system_prompt()
        + " 特别要求：如果输入含有 ⟦P0⟧、⟦P1⟧ 等保护标记，译文必须包含每一个保护标记，数量和编号完全一致。"
        + " 这些标记代表游戏变量或条件语法，不能省略。"
    )


def glossary_references_for_batch(batch: list[dict[str, str]], glossary_map: dict[str, str], max_refs: int = 80) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    texts = [row["英文原文"] for row in batch]
    for term, zh in sorted(glossary_map.items(), key=lambda item: len(item[0]), reverse=True):
        if len(refs) >= max_refs:
            break
        if term in seen or not zh:
            continue
        if any(term != text and term in text for text in texts):
            refs.append({"en": term, "zh": zh})
            seen.add(term)
    return refs


def translate_single_dictionary_row(
    row: dict[str, str],
    glossary_map: dict[str, str],
    args: argparse.Namespace,
    api_key: str,
) -> str:
    masked_text, placeholder_list = mask_placeholders(row["英文原文"])
    payload = {
        "task": "translate_single_game_text_strict_placeholders",
        "style": "史诗叙事风；系统文本清楚短句；专名全部中文化",
        "placeholder_rule": "输出必须包含输入中的每个 ⟦P#⟧ 保护标记，编号和数量完全一致。",
        "glossary": glossary_references_for_batch([row], glossary_map),
        "items": [
            {
                "id": row["词条ID"],
                "text": masked_text,
                "categories": row["分类列表"],
                "modules": row["模块列表"],
            }
        ],
    }
    for _ in range(args.retries):
        single = call_translation_api(api_key, strict_dictionary_system_prompt(), payload, args.timeout, args.retries)
        if not single:
            continue
        translated = unmask_placeholders(single[0]["zh"], placeholder_list)
        if placeholder_safe(row["英文原文"], translated):
            return translated
    raise RuntimeError(f"single-row placeholder repair failed for {row['词条ID']}")


def translate_glossary(export_dir: Path, args: argparse.Namespace, api_key: str) -> list[dict[str, str]]:
    source_path = export_dir / "术语表.csv"
    output_path = export_dir / "术语表_已翻译.csv"
    cache_path = export_dir / "翻译缓存" / "术语翻译.jsonl"
    rows = read_csv(source_path)
    cached = load_jsonl_map(cache_path, "术语ID", "统一中文译名")
    pending = [row for row in rows if row["术语ID"] not in cached]

    for batch_index, batch in enumerate(chunk_items(pending, "英文术语", args.glossary_batch_size, args.max_chars), start=1):
        payload = {
            "task": "translate_glossary_terms",
            "style": "史诗叙事风，术语短且稳定，全部中文化",
            "items": [
                {
                    "id": row["术语ID"],
                    "text": row["英文术语"],
                    "type": row["术语类型"],
                    "priority": row["优先级"],
                    "categories": row["分类列表"],
                }
                for row in batch
            ],
        }
        translations = call_translation_api(api_key, glossary_system_prompt(), payload, args.timeout, args.retries)
        translation_map = {item["id"]: item["zh"] for item in translations}
        missing = [row["术语ID"] for row in batch if row["术语ID"] not in translation_map]
        if missing:
            raise RuntimeError(f"glossary batch missing translations: {missing[:10]}")
        for row in batch:
            translated = translation_map[row["术语ID"]]
            cached[row["术语ID"]] = translated
            append_jsonl(cache_path, {"术语ID": row["术语ID"], "英文术语": row["英文术语"], "统一中文译名": translated})
        if batch_index % args.save_every == 0:
            write_translated_glossary(output_path, rows, cached)
            print(f"glossary_progress={len(cached)}/{len(rows)}")
        time.sleep(args.sleep)

    write_translated_glossary(output_path, rows, cached)
    print(f"glossary_done={len(cached)}/{len(rows)}")
    return read_csv(output_path)


def write_translated_glossary(path: Path, rows: list[dict[str, str]], translations: dict[str, str]) -> None:
    output_rows = []
    for row in rows:
        translated = translations.get(row["术语ID"], row["统一中文译名"])
        output_rows.append({**row, "统一中文译名": translated, "备注": "已翻译" if translated else row["备注"]})
    write_csv(path, output_rows, GLOSSARY_COLUMNS)


def translate_dictionary(export_dir: Path, glossary_rows: list[dict[str, str]], args: argparse.Namespace, api_key: str) -> list[dict[str, str]]:
    source_path = export_dir / "全量翻译词典.csv"
    output_path = export_dir / "全量翻译词典_已翻译.csv"
    cache_path = export_dir / "翻译缓存" / "词典翻译.jsonl"
    rows = read_csv(source_path)
    glossary_map = {row["英文术语"]: row["统一中文译名"] for row in glossary_rows if row["统一中文译名"]}
    cached = load_jsonl_map(cache_path, "词条ID", "中文译文")

    for row in rows:
        if row["词条ID"] not in cached and row["英文原文"] in glossary_map:
            translated = glossary_map[row["英文原文"]]
            cached[row["词条ID"]] = translated
            append_jsonl(cache_path, {"词条ID": row["词条ID"], "英文原文": row["英文原文"], "中文译文": translated})

    pending = [row for row in rows if row["词条ID"] not in cached]
    for batch_index, batch in enumerate(chunk_items(pending, "英文原文", args.dictionary_batch_size, args.max_chars), start=1):
        refs = glossary_references_for_batch(batch, glossary_map)
        masked_by_id: dict[str, list[str]] = {}
        items = []
        for row in batch:
            masked_text, placeholder_list = mask_placeholders(row["英文原文"])
            masked_by_id[row["词条ID"]] = placeholder_list
            items.append(
                {
                    "id": row["词条ID"],
                    "text": masked_text,
                    "categories": row["分类列表"],
                    "modules": row["模块列表"],
                }
            )
        payload = {
            "task": "translate_game_text",
            "style": "史诗叙事风；系统文本清楚短句；专名全部中文化",
            "glossary": refs,
            "items": items,
        }
        translations = call_translation_api(api_key, dictionary_system_prompt(), payload, args.timeout, args.retries)
        translation_map = {item["id"]: item["zh"] for item in translations}
        missing = [row["词条ID"] for row in batch if row["词条ID"] not in translation_map]
        if missing:
            row_by_id = {row["词条ID"]: row for row in batch}
            for missing_id in missing:
                row = row_by_id[missing_id]
                masked_text, placeholder_list = mask_placeholders(row["英文原文"])
                single_payload = {
                    "task": "translate_single_game_text",
                    "style": "史诗叙事风；系统文本清楚短句；专名全部中文化",
                    "glossary": glossary_references_for_batch([row], glossary_map),
                    "items": [
                        {
                            "id": row["词条ID"],
                            "text": masked_text,
                            "categories": row["分类列表"],
                            "modules": row["模块列表"],
                        }
                    ],
                }
                single = call_translation_api(api_key, dictionary_system_prompt(), single_payload, args.timeout, args.retries)
                if single:
                    translation_map[missing_id] = unmask_placeholders(single[0]["zh"], placeholder_list)
            missing = [row["词条ID"] for row in batch if row["词条ID"] not in translation_map]
            if missing:
                raise RuntimeError(f"dictionary batch missing translations: {missing[:10]}")
        for row in batch:
            translated = unmask_placeholders(translation_map[row["词条ID"]], masked_by_id[row["词条ID"]])
            if not placeholder_safe(row["英文原文"], translated):
                translated = translate_single_dictionary_row(row, glossary_map, args, api_key)
            cached[row["词条ID"]] = translated
            append_jsonl(cache_path, {"词条ID": row["词条ID"], "英文原文": row["英文原文"], "中文译文": translated})
        if batch_index % args.save_every == 0:
            write_translated_dictionary(output_path, rows, cached)
            print(f"dictionary_progress={len(cached)}/{len(rows)}")
        time.sleep(args.sleep)

    write_translated_dictionary(output_path, rows, cached)
    print(f"dictionary_done={len(cached)}/{len(rows)}")
    return read_csv(output_path)


def write_translated_dictionary(path: Path, rows: list[dict[str, str]], translations: dict[str, str]) -> None:
    output_rows = []
    for row in rows:
        translated = translations.get(row["词条ID"], row["中文译文"])
        output_rows.append(
            {
                **row,
                "中文译文": translated,
                "翻译状态": "已翻译" if translated else row["翻译状态"],
                "备注": "AI全新翻译" if translated else row["备注"],
            }
        )
    write_csv(path, output_rows, DICTIONARY_COLUMNS)


def build_text_translation_map(dictionary_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {
        row["英文原文"]: {
            "中文译文": row["中文译文"],
            "翻译状态": row["翻译状态"],
        }
        for row in dictionary_rows
    }


def write_text_tables(export_dir: Path, dictionary_rows: list[dict[str, str]]) -> None:
    translation_map = build_text_translation_map(dictionary_rows)
    for source_name, output_name in [
        ("全部英文文本_当前有效.csv", "全部英文文本_当前有效_带译文.csv"),
        ("战帆DLC英文文本.csv", "战帆DLC英文文本_带译文.csv"),
    ]:
        rows = read_csv(export_dir / source_name)
        output_rows = []
        for row in rows:
            translated = translation_map.get(row["英文原文"], {"中文译文": "", "翻译状态": "待翻译"})
            output_rows.append({**row, **translated})
        write_csv(export_dir / output_name, output_rows, TRANSLATED_EFFECTIVE_COLUMNS)


def source_group_name(source_file: str) -> str:
    name = Path(source_file).name
    stem = name[:-4] if name.lower().endswith(".xml") else name
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem)
    return stem or "strings"


def write_utf16_xml(path: Path, string_rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '<?xml version="1.0" encoding="utf-16"?>',
        '<base xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" type="string">',
        " <tags>",
        f'  <tag language="{LANGUAGE_ID}"/>',
        " </tags>",
        " <strings>",
    ]
    for string_id, text in string_rows:
        escaped_id = html.escape(string_id, quote=True)
        escaped_text = html.escape(text, quote=True)
        lines.append(f'  <string id="{escaped_id}" text="{escaped_text}"/>')
    lines.extend([" </strings>", "</base>"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-16")


def write_language_data(path: Path, language_files: list[str]) -> None:
    lines = ['<?xml version="1.0" encoding="utf-16"?>', f'<LanguageData id="{LANGUAGE_ID}">']
    for language_file in language_files:
        lines.append(f'  <LanguageFile xml_path="CNs/{language_file}" />')
    lines.append("</LanguageData>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-16")


def write_submodule(path: Path) -> None:
    content = f"""<?xml version="1.0" encoding="utf-8"?>
<Module>
  <Name value="{MODULE_NAME}" />
  <Id value="{MODULE_ID}" />
  <Version value="v1.0.0" />
  <ModuleCategory value="Singleplayer" />
  <ModuleType value="Community" />
  <DependedModules>
    <DependedModule Id="Native" Optional="false" />
    <DependedModule Id="SandBoxCore" Optional="false" />
    <DependedModule Id="Sandbox" Optional="false" />
    <DependedModule Id="StoryMode" Optional="false" />
    <DependedModule Id="CustomBattle" Optional="true" />
    <DependedModule Id="BirthAndDeath" Optional="true" />
    <DependedModule Id="Multiplayer" Optional="true" />
    <DependedModule Id="NavalDLC" Optional="true" />
  </DependedModules>
  <SubModules />
</Module>
"""
    path.write_text(content, encoding="utf-8")


def build_chinese_module(modules_root: Path, export_dir: Path, dictionary_rows: list[dict[str, str]]) -> None:
    effective_rows = read_csv(export_dir / "全部英文文本_当前有效.csv")
    translation_map = build_text_translation_map(dictionary_rows)
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    written_ids: set[str] = set()
    skipped_rows: list[dict[str, str]] = []

    for row in effective_rows:
        string_id = row["字符串ID"]
        translated = translation_map.get(row["英文原文"], {}).get("中文译文", "")
        if not string_id or not translated:
            skipped_rows.append(row)
            continue
        if string_id in written_ids:
            continue
        written_ids.add(string_id)
        group = source_group_name(row["来源文件"])
        grouped[group].append((string_id, translated))

    module_root = modules_root / MODULE_ID
    language_root = module_root / "ModuleData" / "Languages"
    cns_root = language_root / "CNs"
    cns_root.mkdir(parents=True, exist_ok=True)
    for stale in cns_root.glob("*.xml"):
        stale.unlink()

    language_files: list[str] = []
    for group, string_rows in sorted(grouped.items()):
        filename = f"{group}-zho-CN.xml"
        write_utf16_xml(cns_root / filename, string_rows)
        language_files.append(filename)
    write_language_data(language_root / "language_data.xml", language_files)
    write_submodule(module_root / "SubModule.xml")
    write_csv(export_dir / "未写入XML词条.csv", skipped_rows, list(effective_rows[0].keys()) if effective_rows else [])


def validate_outputs(modules_root: Path, export_dir: Path, dictionary_rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if len(dictionary_rows) != 23591:
        errors.append(f"词典行数不是23591：{len(dictionary_rows)}")
    for row in dictionary_rows:
        if not row["中文译文"]:
            errors.append(f"中文译文为空：{row['词条ID']}")
            break
        if row["翻译状态"] != "已翻译":
            errors.append(f"翻译状态异常：{row['词条ID']}")
            break
        if not placeholder_safe(row["英文原文"], row["中文译文"]):
            errors.append(f"占位符不一致：{row['词条ID']}")
            break

    seen_texts = Counter(row["英文原文"] for row in dictionary_rows)
    duplicate_count = sum(1 for count in seen_texts.values() if count > 1)
    if duplicate_count:
        errors.append(f"英文原文重复：{duplicate_count}")

    module_root = modules_root / MODULE_ID
    for xml_path in module_root.rglob("*.xml"):
        try:
            ET.parse(xml_path)
        except Exception as exc:
            errors.append(f"XML解析失败：{xml_path} {exc}")
            break
    return errors


def write_validation_report(export_dir: Path, errors: list[str], dictionary_rows: list[dict[str, str]]) -> None:
    translated = sum(1 for row in dictionary_rows if row["中文译文"])
    status_done = sum(1 for row in dictionary_rows if row["翻译状态"] == "已翻译")
    lines = [
        "# 全量AI翻译验证报告",
        "",
        f"词典总行数：{len(dictionary_rows)}",
        f"中文译文非空行数：{translated}",
        f"已翻译状态行数：{status_done}",
        f"验证错误数：{len(errors)}",
        "",
        "验证结论：通过" if not errors else "验证结论：未通过",
    ]
    if errors:
        lines.extend(["", "错误："])
        lines.extend(f"- {error}" for error in errors)
    (export_dir / "全量AI翻译验证报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--glossary-batch-size", type=int, default=40)
    parser.add_argument("--dictionary-batch-size", type=int, default=30)
    parser.add_argument("--max-chars", type=int, default=6500)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--save-every", type=int, default=10)
    parser.add_argument("--skip-glossary", action="store_true")
    parser.add_argument("--skip-translation", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get(API_KEY_ENV)
    if not api_key and not args.skip_translation:
        raise RuntimeError(f"missing {API_KEY_ENV}")

    modules_root = Path(__file__).resolve().parent
    export_dir = modules_root / EXPORT_DIR_NAME

    if args.skip_glossary and (export_dir / "术语表_已翻译.csv").exists():
        glossary_rows = read_csv(export_dir / "术语表_已翻译.csv")
    elif args.skip_translation:
        glossary_rows = read_csv(export_dir / "术语表.csv")
    else:
        glossary_rows = translate_glossary(export_dir, args, api_key)

    if args.skip_translation and (export_dir / "全量翻译词典_已翻译.csv").exists():
        dictionary_rows = read_csv(export_dir / "全量翻译词典_已翻译.csv")
    elif args.skip_translation:
        dictionary_rows = read_csv(export_dir / "全量翻译词典.csv")
    else:
        dictionary_rows = translate_dictionary(export_dir, glossary_rows, args, api_key)

    if all(row["中文译文"] for row in dictionary_rows):
        write_text_tables(export_dir, dictionary_rows)
        build_chinese_module(modules_root, export_dir, dictionary_rows)

    errors = validate_outputs(modules_root, export_dir, dictionary_rows) if all(row["中文译文"] for row in dictionary_rows) else []
    write_validation_report(export_dir, errors, dictionary_rows)

    print(f"glossary_rows={len(glossary_rows)}")
    print(f"dictionary_rows={len(dictionary_rows)}")
    print(f"translated_rows={sum(1 for row in dictionary_rows if row['中文译文'])}")
    print(f"validation_errors={len(errors)}")
    print(f"export_dir={export_dir}")
    print(f"module_dir={modules_root / MODULE_ID}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
