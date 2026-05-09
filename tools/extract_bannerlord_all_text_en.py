from __future__ import annotations

import csv
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


OFFICIAL_MODULES = [
    "Native",
    "SandBoxCore",
    "SandBox",
    "StoryMode",
    "CustomBattle",
    "BirthAndDeath",
    "Multiplayer",
    "NavalDLC",
]

MODULE_RANK = {module: index for index, module in enumerate(OFFICIAL_MODULES)}

NON_ENGLISH_LANGUAGE_DIRS = {
    "BR",
    "CNs",
    "CNt",
    "DE",
    "FR",
    "IT",
    "JP",
    "KO",
    "PL",
    "RU",
    "SP",
    "TR",
}

OUTPUT_DIR_NAME = "bannerlord_text_en_exports"
CHINESE_OUTPUT_DIR_NAME = "骑砍2战帆英文文本导出"

RAW_COLUMNS = [
    "row_id",
    "scope",
    "module",
    "category",
    "sub_category",
    "source_file",
    "xml_path",
    "record_tag",
    "record_id",
    "field",
    "string_id",
    "text_en",
]

SUMMARY_COLUMNS = ["category", "module", "rows"]

CHINESE_COLUMN_NAMES = {
    "row_id": "行号",
    "scope": "范围",
    "module": "模块",
    "category": "分类",
    "sub_category": "子分类",
    "source_file": "来源文件",
    "xml_path": "XML路径",
    "record_tag": "记录标签",
    "record_id": "记录ID",
    "field": "字段",
    "string_id": "字符串ID",
    "text_en": "英文原文",
    "rows": "行数",
    "error": "错误",
}

CHINESE_CATEGORY_NAMES = {
    "character": "角色人物",
    "dialogue": "对话文本",
    "encyclopedia_lore": "百科世界观",
    "item_equipment": "物品装备",
    "kingdom_culture_clan": "国家文化家族",
    "misc": "其他文本",
    "multiplayer": "多人模式",
    "quest_story": "任务剧情",
    "scene_asset": "场景资源",
    "settlement": "定居点文本",
    "ship_naval": "舰船航海",
    "system_string": "系统文本",
    "troop_party": "部队队伍",
    "tutorial_notification": "教程通知",
    "ui_menu": "界面菜单",
}

CHINESE_SCOPE_NAMES = {
    "base": "原版",
    "dlc": "战帆DLC",
}

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

LOCALIZED_RE = re.compile(r"^\{=([^}]+)\}(.*)$", re.DOTALL)
PLACEHOLDER_IDS = {"*", "!"}

HUMAN_ATTR_NAMES = {
    "text",
    "name",
    "title",
    "description",
    "hint",
    "tooltip",
    "message",
    "caption",
    "label",
    "content",
    "displayname",
    "display_name",
    "singular",
    "plural",
}

CONTEXT_ID_ATTRS = [
    "id",
    "ID",
    "Id",
    "name",
    "Name",
    "key",
    "Key",
    "id_string",
    "string_id",
]

SKIP_TEXT_PREFIXES = (
    "@",
    "!",
    "#",
    "$",
    "\\",
    "/",
)


def is_under_skipped_language_dir(path: Path, module_root: Path) -> bool:
    try:
        parts = path.relative_to(module_root).parts
    except ValueError:
        return False
    for index, part in enumerate(parts):
        if part == "Languages" and index + 1 < len(parts):
            language_part = parts[index + 1]
            if language_part in NON_ENGLISH_LANGUAGE_DIRS:
                return True
            if language_part == "VoicedLines":
                return True
    return False


def is_language_root_file(path: Path, module_root: Path) -> bool:
    try:
        parts = path.relative_to(module_root).parts
    except ValueError:
        return False
    return len(parts) >= 3 and parts[-2] == "Languages" and parts[-1].lower() != "language_data.xml"


def normalize_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def parse_localized(raw_value: str) -> tuple[str, str] | None:
    match = LOCALIZED_RE.match(raw_value)
    if not match:
        return None
    string_id = match.group(1)
    text = clean_text(match.group(2))
    if string_id in PLACEHOLDER_IDS:
        string_id = ""
    return string_id, text


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def looks_like_human_text(value: str, field_name: str, language_root: bool) -> bool:
    text = clean_text(value)
    if not text:
        return False
    if text.startswith(SKIP_TEXT_PREFIXES):
        return False
    if text.lower() in {"true", "false", "none", "null"}:
        return False
    if re.fullmatch(r"[-+]?\d+(\.\d+)?", text):
        return False
    if re.fullmatch(r"[A-Z]", text):
        return False
    if not language_root:
        return False
    normalized_field = field_name.lower().replace("-", "_")
    if normalized_field not in HUMAN_ATTR_NAMES:
        return False
    if any(separator in text for separator in ("\\", "/", "::")):
        return False
    if re.fullmatch(r"[A-Za-z0-9_.:-]+", text) and "_" in text:
        return False
    return any(ch.isalpha() for ch in text)


def category_for(module: str, relative_file: str, record_tag: str, record_id: str, field: str) -> tuple[str, str]:
    lowered_file = relative_file.lower()
    lowered_record = record_id.lower()
    lowered_field = field.lower()
    source_name = Path(relative_file).name.lower()

    if module == "Multiplayer" or "multiplayer" in lowered_file:
        return "multiplayer", source_name
    if "dialog" in lowered_file or "conversation" in lowered_file or "dialog" in lowered_record:
        return "dialogue", source_name
    if "quest" in lowered_file or "quest" in lowered_record or "story" in lowered_file:
        return "quest_story", source_name
    if "encyclopedia" in lowered_file or "encyclopedia" in lowered_record:
        return "encyclopedia_lore", source_name
    if "settlement" in lowered_file or "village" in lowered_file or "town" in lowered_file:
        return "settlement", source_name
    if any(token in lowered_file for token in ("kingdom", "culture", "clan")):
        return "kingdom_culture_clan", source_name
    if any(token in lowered_file for token in ("hero", "lord", "character", "wanderer", "companion")):
        return "character", source_name
    if any(token in lowered_file for token in ("item", "weapon", "equipment", "crafting", "armor")):
        return "item_equipment", source_name
    if any(token in lowered_file for token in ("ship", "naval", "sail", "port", "boarding")):
        return "ship_naval", source_name
    if any(token in lowered_file for token in ("partytemplate", "partytemplates", "troop", "npc")):
        return "troop_party", source_name
    if any(token in lowered_file for token in ("gui", "prefabs", "launcher", "viewmodel", "gauntlet", "brush")):
        return "ui_menu", source_name
    if any(token in lowered_file for token in ("tutorial", "notification", "hint")) or any(
        token in lowered_field for token in ("hint", "tooltip")
    ):
        return "tutorial_notification", source_name
    if any(token in lowered_file for token in ("sceneobj", "atmospheres", "prefabs", "music", "sound")):
        return "scene_asset", source_name
    if "module_strings" in lowered_file or "common_strings" in lowered_file or record_tag == "string":
        return "system_string", source_name
    return "misc", source_name


def context_id_from_attrs(attrs: dict[str, str], inherited_id: str) -> str:
    for attr in CONTEXT_ID_ATTRS:
        value = attrs.get(attr)
        if value:
            localized = parse_localized(value)
            if localized:
                _, text = localized
                return text or inherited_id
            return value
    return inherited_id


def make_row(
    row_id: int,
    module: str,
    relative_file: str,
    xml_path: str,
    record_tag: str,
    record_id: str,
    field: str,
    string_id: str,
    text_en: str,
) -> dict[str, str]:
    category, sub_category = category_for(module, relative_file, record_tag, record_id, field)
    return {
        "row_id": str(row_id),
        "scope": "dlc" if module == "NavalDLC" else "base",
        "module": module,
        "category": category,
        "sub_category": sub_category,
        "source_file": relative_file,
        "xml_path": xml_path,
        "record_tag": record_tag,
        "record_id": record_id,
        "field": field,
        "string_id": string_id,
        "text_en": text_en,
    }


def extract_from_element(
    rows: list[dict[str, str]],
    module: str,
    relative_file: str,
    elem: ET.Element,
    xml_path: str,
    inherited_record_id: str,
    row_counter: list[int],
    language_root: bool,
) -> None:
    tag = normalize_tag(elem.tag)
    record_id = context_id_from_attrs(elem.attrib, inherited_record_id)

    for attr_name, attr_value in elem.attrib.items():
        if attr_value is None:
            continue
        raw_value = clean_text(attr_value)
        if not raw_value:
            continue
        localized = parse_localized(raw_value)
        string_id = ""
        text = ""
        if localized:
            string_id, text = localized
        elif tag == "string" and attr_name == "text":
            text = raw_value
            string_id = elem.attrib.get("id", "")
        elif language_root and looks_like_human_text(raw_value, attr_name, language_root):
            text = raw_value
            if tag == "string":
                string_id = elem.attrib.get("id", "")
        if not text:
            continue
        if attr_name in {"id", "ID", "Id"} and tag != "string" and not localized:
            continue
        row_counter[0] += 1
        rows.append(
            make_row(
                row_counter[0],
                module,
                relative_file,
                xml_path,
                tag,
                record_id,
                f"attr:{attr_name}",
                string_id,
                text,
            )
        )

    text_value = clean_text(elem.text)
    localized_text = parse_localized(text_value) if text_value else None
    if localized_text:
        string_id, text = localized_text
    elif tag in {"string", "text", "description", "hint", "tooltip", "message"} and looks_like_human_text(
        text_value, tag, language_root
    ):
        string_id = elem.attrib.get("id", "")
        text = text_value
    else:
        string_id = ""
        text = ""
    if text:
        row_counter[0] += 1
        rows.append(
            make_row(
                row_counter[0],
                module,
                relative_file,
                xml_path,
                tag,
                record_id,
                "text",
                string_id,
                text,
            )
        )

    child_counts: Counter[str] = Counter()
    for child in list(elem):
        child_tag = normalize_tag(child.tag)
        child_counts[child_tag] += 1
        child_path = f"{xml_path}/{child_tag}[{child_counts[child_tag]}]"
        extract_from_element(
            rows,
            module,
            relative_file,
            child,
            child_path,
            record_id,
            row_counter,
            language_root,
        )


def extract_xml_file(path: Path, module_root: Path, modules_root: Path, rows: list[dict[str, str]], errors: list[dict[str, str]]) -> None:
    if is_under_skipped_language_dir(path, module_root):
        return
    module = module_root.name
    relative_file = path.relative_to(modules_root).as_posix()
    language_root = is_language_root_file(path, module_root)
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        errors.append(
            {
                "module": module,
                "source_file": relative_file,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return
    row_counter = [len(rows)]
    root_tag = normalize_tag(root.tag)
    extract_from_element(rows, module, relative_file, root, f"/{root_tag}[1]", "", row_counter, language_root)


def effective_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    chosen: dict[str, dict[str, str]] = {}
    for row in rows:
        string_id = row["string_id"]
        if string_id:
            key = f"id:{string_id}"
        else:
            key = "loc:{module}:{source_file}:{xml_path}:{field}:{text_en}".format(**row)
        current = chosen.get(key)
        if current is None:
            chosen[key] = row
            continue
        current_rank = (MODULE_RANK.get(current["module"], -1), int(current["row_id"]))
        new_rank = (MODULE_RANK.get(row["module"], -1), int(row["row_id"]))
        if new_rank >= current_rank:
            chosen[key] = row
    return sorted(chosen.values(), key=lambda item: (item["category"], item["module"], item["source_file"], int(item["row_id"])))


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def to_chinese_row(row: dict[str, str], columns: list[str]) -> dict[str, str]:
    chinese_row: dict[str, str] = {}
    for column in columns:
        chinese_column = CHINESE_COLUMN_NAMES[column]
        value = row.get(column, "")
        if column == "category":
            value = CHINESE_CATEGORY_NAMES.get(value, value)
        elif column == "scope":
            value = CHINESE_SCOPE_NAMES.get(value, value)
        chinese_row[chinese_column] = value
    return chinese_row


def write_chinese_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    chinese_columns = [CHINESE_COLUMN_NAMES[column] for column in columns]
    chinese_rows = [to_chinese_row(row, columns) for row in rows]
    write_csv(path, chinese_rows, chinese_columns)


def write_category_files(output_dir: Path, rows: list[dict[str, str]]) -> None:
    category_dir = output_dir / "categories"
    if category_dir.exists():
        for stale_file in category_dir.glob("*.csv"):
            stale_file.unlink()
    by_category: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)
    for category, category_rows in sorted(by_category.items()):
        write_csv(category_dir / f"{category}.csv", category_rows, RAW_COLUMNS)


def write_chinese_category_files(output_dir: Path, rows: list[dict[str, str]]) -> None:
    category_dir = output_dir / "分类"
    if category_dir.exists():
        for stale_file in category_dir.glob("*.csv"):
            stale_file.unlink()
    by_category: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)
    for category, category_rows in sorted(by_category.items()):
        category_name = CHINESE_CATEGORY_NAMES.get(category, category)
        write_chinese_csv(category_dir / f"{category_name}.csv", category_rows, RAW_COLUMNS)


def compact_join(values: set[str]) -> str:
    return "；".join(sorted(value for value in values if value))


def build_translation_dictionary(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[str, dict[str, object]] = {}
    ordered_texts: list[str] = []
    for row in rows:
        text = row["text_en"]
        if text not in grouped:
            grouped[text] = {
                "string_ids": set(),
                "categories": set(),
                "modules": set(),
                "count": 0,
                "source_file": row["source_file"],
                "record_id": row["record_id"],
            }
            ordered_texts.append(text)
        group = grouped[text]
        group["count"] = int(group["count"]) + 1
        if row["string_id"]:
            group["string_ids"].add(row["string_id"])  # type: ignore[union-attr]
        group["categories"].add(CHINESE_CATEGORY_NAMES.get(row["category"], row["category"]))  # type: ignore[union-attr]
        group["modules"].add(row["module"])  # type: ignore[union-attr]

    dictionary_rows: list[dict[str, str]] = []
    for index, text in enumerate(ordered_texts, start=1):
        group = grouped[text]
        dictionary_rows.append(
            {
                "词条ID": f"T{index:06d}",
                "英文原文": text,
                "中文译文": "",
                "字符串ID列表": compact_join(group["string_ids"]),  # type: ignore[arg-type]
                "分类列表": compact_join(group["categories"]),  # type: ignore[arg-type]
                "模块列表": compact_join(group["modules"]),  # type: ignore[arg-type]
                "出现次数": str(group["count"]),
                "来源文件示例": str(group["source_file"]),
                "记录ID示例": str(group["record_id"]),
                "翻译状态": "待翻译",
                "备注": "",
            }
        )
    return dictionary_rows


def write_readme(output_dir: Path, raw_rows: list[dict[str, str]], effective: list[dict[str, str]], errors: list[dict[str, str]]) -> None:
    category_counts = Counter(row["category"] for row in effective)
    module_counts = Counter(row["module"] for row in effective)
    lines = [
        "# Bannerlord English Text Export",
        "",
        "Scope: official base modules plus NavalDLC. Third-party modules and non-English language folders are excluded.",
        "",
        "Outputs:",
        "- bannerlord_all_text_en_raw.csv: every extracted English text occurrence.",
        "- bannerlord_all_text_en_effective.csv: one effective row per string id, with NavalDLC taking precedence over earlier official modules.",
        "- bannerlord_naval_dlc_text_en.csv: effective rows whose source module is NavalDLC.",
        "- categories/*.csv: effective rows split by category.",
        "- bannerlord_text_en_summary.csv: category and module row counts.",
        "- bannerlord_text_en_parse_errors.csv: XML files that could not be parsed.",
        "",
        f"Raw rows: {len(raw_rows)}",
        f"Effective rows: {len(effective)}",
        f"Parse errors: {len(errors)}",
        "",
        "Effective rows by category:",
    ]
    for category, count in sorted(category_counts.items()):
        lines.append(f"- {category}: {count}")
    lines.extend(["", "Effective rows by module:"])
    for module, count in sorted(module_counts.items()):
        lines.append(f"- {module}: {count}")
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_chinese_readme(
    output_dir: Path,
    raw_rows: list[dict[str, str]],
    effective: list[dict[str, str]],
    naval_dlc_rows: list[dict[str, str]],
    dictionary_rows: list[dict[str, str]],
    errors: list[dict[str, str]],
) -> None:
    category_counts = Counter(row["category"] for row in effective)
    module_counts = Counter(row["module"] for row in effective)
    lines = [
        "# 骑砍2战帆英文文本导出",
        "",
        "范围：官方原版模块加 NavalDLC。第三方 Mod 与非英文语言目录已排除。",
        "",
        "输出文件：",
        "- 全部英文文本_原始出现.csv：所有抽取到的英文文本出现位置。",
        "- 全部英文文本_当前有效.csv：按字符串ID去重后的当前有效英文文本，同ID文本以 NavalDLC 为优先。",
        "- 战帆DLC英文文本.csv：来源模块为 NavalDLC 的当前有效英文文本。",
        "- 分类/*.csv：当前有效英文文本按中文分类拆分。",
        "- 分类统计.csv：中文分类与模块行数统计。",
        "- 全量翻译词典.csv：按唯一英文原文合并的待翻译词典，中文译文列留空。",
        "- 解析错误.csv：无法按标准 XML 解析的文件。",
        "",
        f"原始出现行数：{len(raw_rows)}",
        f"当前有效行数：{len(effective)}",
        f"战帆DLC当前有效行数：{len(naval_dlc_rows)}",
        f"全量翻译词典词条数：{len(dictionary_rows)}",
        f"解析错误数：{len(errors)}",
        "",
        "当前有效行数按分类：",
    ]
    for category, count in sorted(category_counts.items(), key=lambda item: CHINESE_CATEGORY_NAMES.get(item[0], item[0])):
        lines.append(f"- {CHINESE_CATEGORY_NAMES.get(category, category)}：{count}")
    lines.extend(["", "当前有效行数按模块："])
    for module, count in sorted(module_counts.items()):
        lines.append(f"- {module}：{count}")
    (output_dir / "说明.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_chinese_outputs(
    output_dir: Path,
    raw_rows: list[dict[str, str]],
    effective: list[dict[str, str]],
    naval_dlc_rows: list[dict[str, str]],
    summary_rows: list[dict[str, str]],
    errors: list[dict[str, str]],
) -> list[dict[str, str]]:
    dictionary_rows = build_translation_dictionary(effective)
    write_chinese_csv(output_dir / "全部英文文本_原始出现.csv", raw_rows, RAW_COLUMNS)
    write_chinese_csv(output_dir / "全部英文文本_当前有效.csv", effective, RAW_COLUMNS)
    write_chinese_csv(output_dir / "战帆DLC英文文本.csv", naval_dlc_rows, RAW_COLUMNS)
    write_chinese_csv(output_dir / "分类统计.csv", summary_rows, SUMMARY_COLUMNS)
    write_chinese_csv(output_dir / "解析错误.csv", errors, ["module", "source_file", "error"])
    write_csv(output_dir / "全量翻译词典.csv", dictionary_rows, DICTIONARY_COLUMNS)
    write_chinese_category_files(output_dir, effective)
    write_chinese_readme(output_dir, raw_rows, effective, naval_dlc_rows, dictionary_rows, errors)
    return dictionary_rows


def main() -> int:
    modules_root = Path(__file__).resolve().parent
    output_dir = modules_root / OUTPUT_DIR_NAME
    chinese_output_dir = modules_root / CHINESE_OUTPUT_DIR_NAME
    rows: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for module in OFFICIAL_MODULES:
        module_root = modules_root / module
        if not module_root.exists():
            errors.append({"module": module, "source_file": "", "error": "module directory missing"})
            continue
        for path in sorted(module_root.rglob("*.xml")):
            extract_xml_file(path, module_root, modules_root, rows, errors)

    effective = effective_rows(rows)
    naval_dlc_rows = [row for row in effective if row["module"] == "NavalDLC"]

    summary_rows: list[dict[str, str]] = []
    summary_counter = Counter((row["category"], row["module"]) for row in effective)
    for (category, module), count in sorted(summary_counter.items()):
        summary_rows.append({"category": category, "module": module, "rows": str(count)})

    write_csv(output_dir / "bannerlord_all_text_en_raw.csv", rows, RAW_COLUMNS)
    write_csv(output_dir / "bannerlord_all_text_en_effective.csv", effective, RAW_COLUMNS)
    write_csv(output_dir / "bannerlord_naval_dlc_text_en.csv", naval_dlc_rows, RAW_COLUMNS)
    write_csv(output_dir / "bannerlord_text_en_summary.csv", summary_rows, SUMMARY_COLUMNS)
    write_csv(output_dir / "bannerlord_text_en_parse_errors.csv", errors, ["module", "source_file", "error"])
    write_category_files(output_dir, effective)
    write_readme(output_dir, rows, effective, errors)
    dictionary_rows = write_chinese_outputs(chinese_output_dir, rows, effective, naval_dlc_rows, summary_rows, errors)

    print(f"raw_rows={len(rows)}")
    print(f"effective_rows={len(effective)}")
    print(f"naval_dlc_effective_rows={len(naval_dlc_rows)}")
    print(f"translation_dictionary_rows={len(dictionary_rows)}")
    print(f"parse_errors={len(errors)}")
    print(f"output_dir={output_dir}")
    print(f"chinese_output_dir={chinese_output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
