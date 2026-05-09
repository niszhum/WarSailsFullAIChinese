from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

import run_bannerlord_ai_translation as base


EXPORT_DIR_NAME = "骑砍2战帆英文文本导出"
API_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/chat/completions")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
API_KEY_ENV = "DEEPSEEK_API_KEY"
PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")
MASKED_PLACEHOLDER_RE = re.compile(r"⟦P\d+⟧")

STYLE_SCOPE_RE = re.compile(r"对话文本|任务剧情|角色人物|国家文化家族|定居点文本|百科世界观|舰船航海")
ALWAYS_POLISH_RE = re.compile(r"对话文本|任务剧情")
TRANSLATIONESE_RE = re.compile(
    r"告知|若|吾|此乃|阁下|于我|于你|于他|于她|追求于|效劳|命你|命令你的|"
    r"将[^，。！？]{0,20}(?:带给|交给|送至|送往)|愿为|以便|从而|之地|之人|之子|之女|"
    r"麾下|甚|未能|加以|进行"
)

POLISH_REPORT_COLUMNS = [
    "词条ID",
    "分类列表",
    "英文原文",
    "润色前",
    "润色后",
    "命中原因",
    "来源文件示例",
]


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


def load_jsonl(path: Path, key_field: str, value_field: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            key = str(item.get(key_field, ""))
            value = str(item.get(value_field, ""))
            if key and value:
                result[key] = value
    return result


def chunk_by_chars(rows: list[dict[str, str]], batch_size: int, max_chars: int) -> list[list[dict[str, str]]]:
    batches: list[list[dict[str, str]]] = []
    batch: list[dict[str, str]] = []
    total = 0
    for row in rows:
        size = len(row["英文原文"]) + len(row["中文译文"])
        if batch and (len(batch) >= batch_size or total + size > max_chars):
            batches.append(batch)
            batch = []
            total = 0
        batch.append(row)
        total += size
    if batch:
        batches.append(batch)
    return batches


def extract_json(raw: str) -> dict:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(raw[start : end + 1])


def call_api(api_key: str, system_prompt: str, payload: dict, timeout: int, retries: int) -> dict:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "temperature": 0.25,
        "response_format": {"type": "json_object"},
    }
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(API_URL, headers=headers, json=body, timeout=timeout)
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(min(60, attempt * attempt * 2))
                continue
            response.raise_for_status()
            return extract_json(response.json()["choices"][0]["message"]["content"])
        except Exception as exc:
            last_error = exc
            time.sleep(min(60, attempt * attempt * 2))
    raise RuntimeError(f"API failed after {retries} retries: {last_error}")


def placeholder_counter(text: str) -> Counter[str]:
    return Counter(PLACEHOLDER_RE.findall(text))


def strict_placeholder_safe(english: str, translation: str) -> bool:
    return placeholder_counter(english) == placeholder_counter(translation)


def mask_text(text: str) -> tuple[str, list[str]]:
    placeholders = PLACEHOLDER_RE.findall(text or "")
    masked = text or ""
    for index, placeholder in enumerate(placeholders):
        masked = masked.replace(placeholder, f"⟦P{index}⟧", 1)
    return masked, placeholders


def unmask_text(text: str, placeholders: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        index = int(token[2:-1])
        if 0 <= index < len(placeholders):
            return placeholders[index]
        return token

    return MASKED_PLACEHOLDER_RE.sub(replace, text)


def normalize_style_locally(text: str, category: str) -> str:
    result = text
    replacements = [
        ("告知你", "告诉你"),
        ("告知", "告诉"),
        ("若你", "如果你"),
        ("若", "如果"),
        ("效劳", "帮忙"),
        ("命你", "让你"),
        ("命令你的", "让你的"),
        ("于我", "对我"),
        ("于你", "对你"),
        ("于他", "对他"),
        ("于她", "对她"),
        ("追求于我", "追求我"),
        ("未能", "没能"),
        ("加以", ""),
        ("进行", ""),
    ]
    for old, new in replacements:
        result = result.replace(old, new)
    if "对话文本" in category or "任务剧情" in category:
        result = result.replace("阁下", "你")
        result = result.replace("请君", "请你")
        result = result.replace("君", "你")
    return result


def candidate_reason(row: dict[str, str]) -> str:
    category = row["分类列表"]
    translation = row["中文译文"]
    if not STYLE_SCOPE_RE.search(category):
        return ""
    if len(row["英文原文"]) <= 48 and len(translation) <= 18 and not ALWAYS_POLISH_RE.search(category):
        return ""
    if ALWAYS_POLISH_RE.search(category):
        return "对话/剧情全量润色"
    matches = sorted(set(TRANSLATIONESE_RE.findall(translation)))
    if matches:
        return "翻译腔命中：" + "、".join(matches[:8])
    return ""


def build_term_rows(export_dir: Path) -> list[dict[str, str]]:
    terms: list[dict[str, str]] = []
    for row in read_csv(export_dir / "文化称呼表.csv"):
        terms.append({"en": row["英文术语"], "zh": row["统一译名"], "type": row["类型"]})
    for row in read_csv(export_dir / "专名音译表.csv"):
        terms.append({"en": row["英文专名"], "zh": row["统一音译"], "type": row["类型"]})
    for row in read_csv(export_dir / "术语表_已翻译.csv"):
        if row.get("英文术语") and row.get("统一中文译名") and row.get("术语类型") in {"person", "ship", "clan", "kingdom", "culture", "settlement"}:
            terms.append({"en": row["英文术语"], "zh": row["统一中文译名"], "type": row["术语类型"]})
    return terms


def relevant_terms(english: str, terms: list[dict[str, str]], limit: int = 24) -> list[dict[str, str]]:
    lowered = english.lower()
    hits = []
    seen = set()
    for row in terms:
        term = row["en"]
        if not term or term in seen:
            continue
        if term.lower() in lowered:
            hits.append(row)
            seen.add(term)
        if len(hits) >= limit:
            break
    return hits


def polish_rows(
    rows: list[dict[str, str]],
    export_dir: Path,
    args: argparse.Namespace,
    api_key: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str]]:
    cache_path = export_dir / "翻译缓存" / "本地化润色.jsonl"
    cached = load_jsonl(cache_path, "词条ID", "中文译文")
    terms = build_term_rows(export_dir)
    reasons = {row["词条ID"]: candidate_reason(row) for row in rows}
    target_ids = {row["词条ID"] for row in rows if reasons[row["词条ID"]]}
    candidates = [row for row in rows if row["词条ID"] in target_ids and row["词条ID"] not in cached]
    system_prompt = (
        "你是游戏汉化二审编辑。任务是在已有中文译文上做本地化润色，不重翻、不扩写、不改变剧情事实。"
        "对话要像人在游戏里说话，去掉翻译腔；人物背景和百科叙事要有中世纪史诗感，但使用自然现代中文，避免文言腔。"
        "优先消除这些表达：告知、若、吾、此、其、乃、阁下、效劳、命你、追求于、之地、之人、将...带给。"
        "不要把音译名中的“尔”改成“你”，不要改动人名、地名、家族名、船名和文化称呼。"
        "系统按钮和纯功能词不在本任务内。文化称呼和专名必须按给定术语保持一致。"
        "必须保留所有 ⟦P#⟧ 占位符，编号和数量完全一致。只输出JSON对象："
        "{\"polished\":[{\"id\":\"...\",\"zh\":\"...\"}]}"
    )
    errors: list[str] = []
    batches = chunk_by_chars(candidates, args.batch_size, args.max_chars)

    def process_batch(batch_index: int, batch: list[dict[str, str]]) -> tuple[int, list[tuple[dict[str, str], str]], list[str]]:
        payload_items = []
        placeholder_by_id: dict[str, list[str]] = {}
        fallback_by_id: dict[str, str] = {}
        for row in batch:
            local_zh = normalize_style_locally(row["中文译文"], row["分类列表"])
            masked_zh, placeholders = mask_text(local_zh)
            masked_en, _ = mask_text(row["英文原文"])
            placeholder_by_id[row["词条ID"]] = placeholders
            fallback_by_id[row["词条ID"]] = local_zh
            payload_items.append(
                {
                    "id": row["词条ID"],
                    "category": row["分类列表"],
                    "reason": reasons[row["词条ID"]],
                    "en": masked_en,
                    "current_zh": masked_zh,
                    "terms": relevant_terms(row["英文原文"], terms),
                }
            )
        result = call_api(api_key, system_prompt, {"task": "localization_style_polish", "items": payload_items}, args.timeout, args.retries)
        polished = result.get("polished", [])
        if not isinstance(polished, list):
            raise RuntimeError("missing polished array")
        by_id = {str(item.get("id", "")): item for item in polished if isinstance(item, dict)}
        output: list[tuple[dict[str, str], str]] = []
        batch_errors: list[str] = []
        for row in batch:
            item = by_id.get(row["词条ID"])
            if not item:
                candidate = fallback_by_id[row["词条ID"]]
            else:
                candidate = str(item.get("zh", "")).strip() or fallback_by_id[row["词条ID"]]
            candidate = unmask_text(candidate, placeholder_by_id[row["词条ID"]])
            if not strict_placeholder_safe(row["英文原文"], candidate):
                candidate = fallback_by_id[row["词条ID"]]
            if not strict_placeholder_safe(row["英文原文"], candidate):
                batch_errors.append(f"{row['词条ID']} placeholder mismatch")
                candidate = row["中文译文"]
            output.append((row, candidate))
        return batch_index, output, batch_errors

    completed = len([item_id for item_id in target_ids if item_id in cached])
    total = len(target_ids)
    if args.workers <= 1:
        for index, batch in enumerate(batches, start=1):
            _, output, batch_errors = process_batch(index, batch)
            errors.extend(batch_errors)
            for row, candidate in output:
                cached[row["词条ID"]] = candidate
                append_jsonl(cache_path, {"词条ID": row["词条ID"], "英文原文": row["英文原文"], "中文译文": candidate})
            completed += len(output)
            print(f"polish_progress={completed}/{total}")
            time.sleep(args.sleep)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_map = {executor.submit(process_batch, index, batch): index for index, batch in enumerate(batches, start=1)}
            for future in as_completed(future_map):
                _, output, batch_errors = future.result()
                errors.extend(batch_errors)
                for row, candidate in output:
                    cached[row["词条ID"]] = candidate
                    append_jsonl(cache_path, {"词条ID": row["词条ID"], "英文原文": row["英文原文"], "中文译文": candidate})
                completed += len(output)
                print(f"polish_progress={completed}/{total}")
                time.sleep(args.sleep)

    output_rows: list[dict[str, str]] = []
    changed_rows: list[dict[str, str]] = []
    for row in rows:
        polished = cached.get(row["词条ID"])
        if polished:
            polished = normalize_style_locally(polished, row["分类列表"])
        else:
            polished = normalize_style_locally(row["中文译文"], row["分类列表"]) if reasons[row["词条ID"]] else row["中文译文"]
        if polished != row["中文译文"]:
            changed_rows.append(
                {
                    "词条ID": row["词条ID"],
                    "分类列表": row["分类列表"],
                    "英文原文": row["英文原文"],
                    "润色前": row["中文译文"],
                    "润色后": polished,
                    "命中原因": reasons[row["词条ID"]],
                    "来源文件示例": row["来源文件示例"],
                }
            )
        output_rows.append({**row, "中文译文": polished, "翻译状态": "已翻译", "备注": "本地化口语与文化风格润色" if reasons[row["词条ID"]] else row["备注"]})
    return output_rows, changed_rows, errors


def write_text_tables(export_dir: Path, dictionary_rows: list[dict[str, str]]) -> None:
    translation_map = base.build_text_translation_map(dictionary_rows)
    for source_name, output_name in [
        ("全部英文文本_当前有效.csv", "全部英文文本_当前有效_带译文.csv"),
        ("战帆DLC英文文本.csv", "战帆DLC英文文本_带译文.csv"),
    ]:
        rows = read_csv(export_dir / source_name)
        output_rows = []
        for row in rows:
            translated = translation_map.get(row["英文原文"], {"中文译文": "", "翻译状态": "待翻译"})
            output_rows.append({**row, **translated})
        write_csv(export_dir / output_name, output_rows, base.TRANSLATED_EFFECTIVE_COLUMNS)


def validate_rows(rows: list[dict[str, str]], changed_rows: list[dict[str, str]], xml_errors: list[str]) -> list[str]:
    errors: list[str] = []
    if len(rows) != 23591:
        errors.append(f"词典行数异常: {len(rows)}")
    empty = [row["词条ID"] for row in rows if not row["中文译文"].strip()]
    if empty:
        errors.append(f"中文译文空值: {empty[:10]}")
    placeholder_bad = [row["词条ID"] for row in rows if not strict_placeholder_safe(row["英文原文"], row["中文译文"])]
    if placeholder_bad:
        errors.append(f"严格占位符错误: {placeholder_bad[:20]}")
    repeated = [row["词条ID"] for row in rows if "菲尔德菲尔德" in row["中文译文"]]
    if repeated:
        errors.append(f"重复替换错误: {repeated[:10]}")
    name_corruption = [
        row["词条ID"]
        for row in rows
        if re.search(r"哈你|沃你|雅你|阿你|克约你|德瑟你|苏你|贝你|格你", row["中文译文"])
    ]
    if name_corruption:
        errors.append(f"疑似音译名被错误改写: {name_corruption[:20]}")
    style_left = [
        row["词条ID"]
        for row in changed_rows
        if ALWAYS_POLISH_RE.search(row["分类列表"]) and re.search(r"告知|吾|汝|阁下|追求于|命你|效劳", row["润色后"])
    ]
    if style_left:
        errors.append(f"对话剧情仍有明显翻译腔: {style_left[:20]}")
    errors.extend(xml_errors)
    return errors


def write_report(export_dir: Path, rows: list[dict[str, str]], changed_rows: list[dict[str, str]], errors: list[str]) -> None:
    lines = [
        "# 本地化口语与文化风格润色验证报告",
        "",
        f"词典总行数：{len(rows)}",
        f"润色变更行数：{len(changed_rows)}",
        f"中文译文空值：{sum(1 for row in rows if not row['中文译文'].strip())}",
        f"占位符错误：{sum(1 for row in rows if not strict_placeholder_safe(row['英文原文'], row['中文译文']))}",
        f"验证错误数：{len(errors)}",
        "",
        "验证结论：通过" if not errors else "验证结论：未通过",
    ]
    if errors:
        lines.extend(["", "错误："])
        lines.extend(f"- {error}" for error in errors)
    (export_dir / "本地化口语与文化风格润色验证报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"missing {API_KEY_ENV}")

    modules_root = Path(__file__).resolve().parent
    export_dir = modules_root / EXPORT_DIR_NAME
    dictionary_rows = read_csv(export_dir / "全量翻译词典_已翻译.csv")
    polished_rows, changed_rows, polish_errors = polish_rows(dictionary_rows, export_dir, args, api_key)

    write_csv(export_dir / "全量翻译词典_已翻译.csv", polished_rows, base.DICTIONARY_COLUMNS)
    write_text_tables(export_dir, polished_rows)
    base.build_chinese_module(modules_root, export_dir, polished_rows)
    xml_errors = base.validate_outputs(modules_root, export_dir, polished_rows)
    errors = polish_errors + validate_rows(polished_rows, changed_rows, xml_errors)
    base.write_validation_report(export_dir, errors, polished_rows)
    write_csv(export_dir / "本地化润色变更表.csv", changed_rows, POLISH_REPORT_COLUMNS)
    write_report(export_dir, polished_rows, changed_rows, errors)

    print(f"dictionary_rows={len(polished_rows)}")
    print(f"changed_rows={len(changed_rows)}")
    print(f"validation_errors={len(errors)}")
    print(f"export_dir={export_dir}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
