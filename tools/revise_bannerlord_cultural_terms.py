from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests

import run_bannerlord_ai_translation as base


EXPORT_DIR_NAME = "骑砍2战帆英文文本导出"
API_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/chat/completions")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
API_KEY_ENV = "DEEPSEEK_API_KEY"
PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")
NORD_ROYAL_MARKERS = [
    "nordvyg",
    "king volbjorn",
    "old king volbjorn",
    "king halthdar",
    "new king halthdar",
    "volbjorn the hungry",
    "halthdar the golden",
    "nord king",
    "nord queen",
    "king and the jarls",
    "king and jarls",
]
NON_NORD_ROYAL_MARKERS = [
    "high king",
    "high queen",
    "battanian high king",
    "battanians",
    "vlandian king",
    "sturgian king",
    "aserai king",
]

CULTURAL_TERM_COLUMNS = ["英文术语", "文化", "类型", "当前译名", "统一译名", "使用规则", "示例"]
SPECIAL_NAME_COLUMNS = ["英文专名", "类型", "当前译名", "统一音译", "使用规则", "来源"]

FIXED_CULTURAL_TERMS = [
    ("jarl", "Nord", "头衔", "领主", "雅尔", "诺德文化头衔，不译作领主。", "jarl of Beinland"),
    ("jarls", "Nord", "头衔", "领主们", "雅尔们", "诺德文化头衔复数。", "his jarls"),
    ("jarlinna", "Nord", "头衔", "女领主", "女雅尔", "诺德女性头衔，不译作女领主。", "a jarlinna"),
    ("king of the Nordvyg", "Nord", "王权称谓", "诺德维格之王", "诺德维格科农格", "诺德维格王权语境使用科农格。", "king of the Nordvyg"),
    ("queen of the Nordvyg", "Nord", "王权称谓", "诺德维格女王", "诺德维格女科农格", "诺德维格王权语境使用女科农格。", "queen of the Nordvyg"),
    ("Kingdom of the Nordvyg", "Nord", "政体名称", "诺德维格王国", "诺德维格科农格领", "保留诺德文化王权称呼。", "Kingdom of the Nordvyg"),
    ("king", "Nord", "王权称谓", "国王", "科农格", "仅在诺德王权上下文使用。", "the king and the jarls"),
    ("queen", "Nord", "王权称谓", "女王", "女科农格", "仅在诺德王权上下文使用。", "queen of the Nordvyg"),
    ("fyrdman", "Nord", "兵种称谓", "民兵", "菲尔德民兵", "诺德征召兵文化称呼。", "Beinlandsk Fyrdman"),
    ("Fyrdman", "Nord", "兵种称谓", "民兵", "菲尔德民兵", "诺德征召兵文化称呼。", "Fyrdman"),
    ("huscarl", "Nord", "兵种称谓", "护卫", "胡斯卡尔", "诺德亲兵称呼。", "Nord Huscarl"),
    ("Huscarl", "Nord", "兵种称谓", "护卫", "胡斯卡尔", "诺德亲兵称呼。", "Nord Huscarl"),
    ("thegn", "Nord", "头衔/兵种", "贵族战士", "塞恩", "诺德/北欧贵族随从称呼。", "Nord Thegn"),
    ("Thegn", "Nord", "头衔/兵种", "贵族战士", "塞恩", "诺德/北欧贵族随从称呼。", "Thegn"),
    ("drengr", "Nord", "兵种称谓", "战士", "德伦格", "诺德勇士称呼。", "Nord Drengr"),
    ("Drengr", "Nord", "兵种称谓", "战士", "德伦格", "诺德勇士称呼。", "Drengr"),
    ("berserkir", "Nord", "兵种称谓", "狂战士", "贝瑟克", "诺德狂战文化称呼。", "Nord Berserkir"),
    ("Berserkir", "Nord", "兵种称谓", "狂战士", "贝瑟克", "诺德狂战文化称呼。", "Berserkir"),
    ("boandi", "Nord", "阶层称谓", "农民", "博安迪", "诺德自由农阶层称呼。", "Nord Boandi"),
    ("Boandi", "Nord", "阶层称谓", "农民", "博安迪", "诺德自由农阶层称呼。", "Boandi"),
    ("skjaldbrestir", "Nord", "兵种称谓", "盾卫", "斯基亚尔德布雷斯蒂尔", "诺德兵种称呼音译。", "Nord Skjaldbrestir"),
    ("Skjaldbrestir", "Nord", "兵种称谓", "盾卫", "斯基亚尔德布雷斯蒂尔", "诺德兵种称呼音译。", "Skjaldbrestir"),
    ("ulfhedinn", "Nord", "兵种称谓", "狼皮战士", "乌尔夫赫丁", "诺德兵种称呼音译。", "Nord Ulfhedinn"),
    ("Ulfhedinn", "Nord", "兵种称谓", "狼皮战士", "乌尔夫赫丁", "诺德兵种称呼音译。", "Ulfhedinn"),
    ("Ulfhednar", "Nord", "兵种称谓", "狼皮战士", "乌尔夫赫德纳尔", "诺德兵种称呼音译。", "Nord Ulfhednar"),
    ("Berserkr", "Nord", "兵种称谓", "狂战士", "贝瑟克尔", "诺德兵种称呼音译。", "Nord Berserkr"),
    ("Bahriyyah", "Aserai", "兵种称谓", "海员", "巴赫里耶", "阿塞莱文化兵种称呼音译。", "Aserai Bahriyyah"),
    ("Skipari", "Battania", "兵种称谓", "船夫", "斯基帕里", "巴旦尼亚/北海语源兵种称呼音译。", "Battanian Skipari"),
    ("Naute", "Empire", "兵种称谓", "水手", "瑙特", "帝国海员称呼音译。", "Imperial Naute"),
    ("Shipmate", "Empire", "兵种称谓", "船友", "希普梅特", "帝国舰员称呼音译。", "Imperial Shipmate"),
    ("Nordvyg", "Nord", "地缘名称", "诺德维格", "诺德维格", "专名音译保留。", "Nordvyg"),
    ("Nords", "Nord", "族群名称", "诺德人", "诺德人", "族群名保留文化称呼。", "the Nords"),
    ("Nordic", "Nord", "文化形容词", "诺德", "诺德", "文化形容词保留。", "Nordic"),
]

FIXED_SPECIAL_NAMES = [
    ("Golden Wasp", "船名", "金蜂号", "戈尔登瓦斯普号", "船名音译，加“号”。", "固定规则"),
    ("Wave-Breaker", "称号/船名", "破浪", "韦夫布雷克", "称号或专名音译。", "固定规则"),
    ("Sea Hounds", "组织名", "海猎犬", "西霍恩德团", "组织名音译，加“团”。", "固定规则"),
    ("Sea Hounds", "组织名", "海狼", "西霍恩德团", "组织名音译，加“团”。", "固定规则"),
    ("Sea Hounds", "组织名", "海犬", "西霍恩德团", "组织名音译，加“团”。", "固定规则"),
    ("Leviathan", "船名/专名", "利维坦", "利维坦", "通行音译保留。", "固定规则"),
    ("Nereid", "船名/专名", "涅瑞伊得", "涅瑞伊得", "通行音译保留。", "固定规则"),
    ("Djinn-King", "船名/称号", "巨灵之王", "金恩金", "专名音译。", "固定规则"),
    ("Lord of the Horns", "船名/称号", "角之主", "洛德奥夫霍恩斯", "专名音译。", "固定规则"),
    ("Good King Bonneric", "船名/称号", "贤王博内里克", "古德金博内里克", "专名音译。", "固定规则"),
    ("Queen Tara", "船名/称号", "塔拉女王", "昆塔拉", "专名音译。", "固定规则"),
    ("Volbjorn the Hungry", "人物称号", "饿狼沃尔比约恩", "沃尔比约恩·亨格里", "人物称号音译。", "固定规则"),
    ("Halthdar the Golden", "人物称号", "金王哈尔斯达尔", "哈尔斯达尔·戈尔登", "人物称号音译。", "固定规则"),
]

ZH_REPLACEMENTS = [
    ("诺德维格之王", "诺德维格科农格"),
    ("诺德维格女王", "诺德维格女科农格"),
    ("诺德维格王国", "诺德维格科农格领"),
    ("饿狼沃尔比约恩", "沃尔比约恩·亨格里"),
    ("金王哈尔斯达尔", "哈尔斯达尔·戈尔登"),
    ("金蜂号", "戈尔登瓦斯普号"),
    ("破浪者", "韦夫布雷克"),
    ("破浪", "韦夫布雷克"),
    ("海猎犬", "西霍恩德团"),
    ("海狼", "西霍恩德团"),
    ("海犬", "西霍恩德团"),
    ("巨灵之王", "金恩金"),
    ("角之主", "洛德奥夫霍恩斯"),
    ("贤王博内里克", "古德金博内里克"),
    ("塔拉女王", "昆塔拉"),
    ("一位领主", "一位雅尔"),
    ("一位女领主", "一位女雅尔"),
    ("新王", "新科农格"),
    ("老国王", "老科农格"),
    ("一国之君", "科农格"),
    ("女领主", "女雅尔"),
    ("领主们", "雅尔们"),
    ("领主", "雅尔"),
    ("国王", "科农格"),
    ("女王", "女科农格"),
    ("民兵", "菲尔德民兵"),
    ("护卫", "胡斯卡尔"),
    ("狂战士", "贝瑟克"),
    ("贵族战士", "塞恩"),
]

PLACEHOLDER_REPAIR_OVERRIDES = {
    "T017201": r"{QUEST_GIVER.LINK}告知你，{?QUEST_GIVER.GENDER}她{?}他{\?}的村庄需要{._}{REQUIRED_ITEM}。{?QUEST_GIVER.GENDER}她{?}他{\?}请求你将{ITEM_COUNT} {.%}{?(ITEM_COUNT > 1)}{PLURAL(REQUIRED_ITEM)}{?}{REQUIRED_ITEM}{\?}{.%}带给{?QUEST_GIVER.GENDER}她{?}他{\?}。{?QUEST_GIVER.GENDER}她{?}他{\?}将按约支付。{PAYMENT_DESCRIPTION}",
    "T017909": r"{QUEST_GIVER.LINK}告诉你，{?QUEST_GIVER.GENDER}她{?}他{\?}的村庄需要{.%}{?(REQUESTED_ANIMAL_AMOUNT > 1)}{PLURAL(SELECTED_ANIMAL)}{?}{SELECTED_ANIMAL}{\?}{.%}。{?QUEST_GIVER.GENDER}她{?}他{\?}说动物送达后，{?QUEST_GIVER.GENDER}她{?}他{\?}将付给你{REWARD_GOLD}{GOLD_ICON}第纳尔。你命令你的{COMPANION.LINK}与{ALTERNATIVE_TROOP_AMOUNT}名部下将{REQUESTED_ANIMAL_AMOUNT} {.%}{?(REQUESTED_ANIMAL_AMOUNT > 1)}{PLURAL(SELECTED_ANIMAL)}{?}{SELECTED_ANIMAL}{\?}{.%}送往{QUEST_GIVER.LINK}。他们将在{RETURN_DAYS}天后归队。",
    "T018066": r"{QUEST_GIVER.LINK}，{QUEST_SETTLEMENT}之{?QUEST_GIVER.GENDER}女士{?}领主{\?}，告诉你{?QUEST_GIVER.GENDER}她{?}他{\?}需要在{?QUEST_GIVER.GENDER}她的{?}他的{\?}驻军中补充更多兵力。{?QUEST_GIVER.GENDER}她{?}他{\?}愿为你的效劳支付{REWARD}{GOLD_ICON}。{?QUEST_GIVER.GENDER}她{?}他{\?}命你将{NUMBER_OF_TROOP_TO_BE_RECRUITED} {TROOP_TYPE}名士兵送至{QUEST_SETTLEMENT}的驻军指挥官处。",
    "T018106": r"你击败了{QUEST_GIVER.LINK}提到的那伙大股匪徒，{?QUEST_GIVER.GENDER}她{?}他{\?}送来{?QUEST_GIVER.GENDER}她的{?}他的{\?}问候、{?QUEST_GIVER.GENDER}她{?}他{\?}承诺的{REWARD_GOLD}{GOLD_ICON}以及一些贸易品作为酬劳。",
    "T018338": r"{?PLAYER_CHILD}你的{?}这个{\?}孩子大部分空闲时间都用{?CHILD.GENDER}她的{?}他的{\?}木剑，与{?CHILD.GENDER}她{?}他{\?}想象中的怪物搏斗。",
    "T018353": r"年轻的{?CHILD.GENDER}女子{?}男子{\?}将在{?CHILD.GENDER}她的{?}他的{\?}外交任务时光中与异邦人士交流，{?CHILD.GENDER}她{?}他{\?}会因此见识更广。",
    "T018468": r"{?QUEST_GIVER.GENDER}莱迪{?}领主{\?} {QUEST_GIVER.NAME} 要求得到你从{?QUEST_GIVER.GENDER}她{?}他{\?}的封地中征收的{TOTAL_REQUESTED_DENARS}{GOLD_ICON}第纳尔。{?QUEST_GIVER.GENDER}她{?}他{\?}已派遣{?QUEST_GIVER.GENDER}她的{?}他的{\?}管家前来收取。若你拒绝，将被视为犯罪，且{?QUEST_GIVER.GENDER}她{?}他{\?}的派系可能向你宣战。",
    "T018556": r"你的孩子天生一副洪亮而悦耳的嗓音，这让{?CHILD.GENDER}她{?}他{\?}看起来比{?CHILD.GENDER}她的{?}他的{\?}实际年龄更成熟睿智。",
    "T018869": r"这位年轻的{?CHILD.GENDER}女子{?}男子{\?}凭借{?CHILD.GENDER}她的{?}他的{\?}魅力跻身贵族圈子，成为盛宴上的座上宾。",
    "T019207": r"{?KING.GENDER}她{?}他{\?}正在从{?KING.GENDER}她的{?}他的{\?}伤势中恢复，可能还需要一段时间，{?KING.GENDER}她{?}他{\?}才能处理国事。",
    "T019239": r"{ISSUE_OWNER.LINK}，{QUEST_SETTLEMENT}的{?ISSUE_OWNER.GENDER}女士{?}领主{\?}告知你，{?ISSUE_OWNER.GENDER}她{?}他{\?}需要为{?ISSUE_OWNER.GENDER}她的{?}他的{\?}驻军补充更多部队。{?ISSUE_OWNER.GENDER}她{?}他{\?}愿为你的效劳支付{REWARD}{GOLD_ICON}。你命同伴向{QUEST_SETTLEMENT}的驻军部署{NUMBER_OF_TROOP_TO_BE_RECRUITED} {TROOP_TYPE}名士兵。",
    "T019526": r"如果{?CURRENT_LIEGE.GENDER}她{?}他{\?}曾经违背了{?CURRENT_LIEGE.GENDER}她的{?}他的{\?}誓言，你就解除了对{?CURRENT_LIEGE.GENDER}她{?}他{\?}的义务。",
    "T019594": r"唉……听说{LORD.LINK}把{?LORD.GENDER}他的{?}她的{\?}屁股交给{OTHER_SIDE}，被打得{?LORD.GENDER}他{?}她{\?}屁滚尿流。时运不济啊，朋友。",
    "T019967": r"{RULER.NAME}的{KINGDOM}不顾{?RULER.GENDER}她的{?}他的{\?}议会反对，将{SETTLEMENT}作为{?RULER.GENDER}她的{?}他的{\?}封地。",
    "T020192": r"{QUEST_GIVER.LINK}，{TARGET_SETTLEMENT}的{?QUEST_GIVER.GENDER}女士{?}领主{\?}告诉你，{?QUEST_GIVER.GENDER}她{?}他{\?}一直受到在{TARGET_SETTLEMENT}与{ORIGIN_SETTLEMENT}之间活动的走私者困扰。你承诺追踪这些走私者并将他们赶出{TARGET_SETTLEMENT}。",
    "T020902": r"{QUEST_GIVER.LINK}告诉你，{?QUEST_GIVER.GENDER}她{?}他{\?}的村庄需要{.%}{?(REQUESTED_ANIMAL_AMOUNT > 1)}{PLURAL(SELECTED_ANIMAL)}{?}{SELECTED_ANIMAL}{\?}{.%}。{?QUEST_GIVER.GENDER}她{?}他{\?}请求你将{REQUESTED_ANIMAL_AMOUNT} {.%}{?(REQUESTED_ANIMAL_AMOUNT > 1)}{PLURAL(SELECTED_ANIMAL)}{?}{SELECTED_ANIMAL}{\?}{.%}带给{?QUEST_GIVER.GENDER}她{?}他{\?}。{?QUEST_GIVER.GENDER}她{?}他{\?}会记下这份帮助。",
    "T021619": r"{QUEST_GIVER.LINK}想要你从{?QUEST_GIVER.GENDER}她{?}他{\?}的封地中收集的{TOTAL_REQUESTED_DENARS}{GOLD_ICON}。你可以亲自将第纳尔交给{?QUEST_GIVER.GENDER}女士{?}领主{\?}，或交给{?QUEST_GIVER.GENDER}女士{?}领主{\?}的管家，管家可在属于{?QUEST_GIVER.GENDER}女士{?}领主{\?}的城堡和城镇中找到。",
    "T021683": r"你行进途中，发现{COMPANION.NAME}在前方等候。{?COMPANION.GENDER}她{?}他{\?}向你致意，报告说{?COMPANION.GENDER}她{?}他{\?}已从{?COMPANION.GENDER}她的{?}他的{\?}任务归来，带回{NUMBER} {?(NUMBER > 1)}名士兵{?}名士兵{\?}，他们已准备好重新加入你的队伍。",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_baseline_dictionary(export_dir: Path) -> list[dict[str, str]]:
    source_rows = read_csv(export_dir / "全量翻译词典.csv")
    cached_translations = load_jsonl(export_dir / "翻译缓存" / "词典翻译.jsonl", "词条ID", "中文译文")
    rows = []
    for row in source_rows:
        translated = cached_translations.get(row["词条ID"], row.get("中文译文", ""))
        rows.append(
            {
                **row,
                "中文译文": translated,
                "翻译状态": "已翻译" if translated else row.get("翻译状态", "待翻译"),
                "备注": "AI全新翻译" if translated else row.get("备注", ""),
            }
        )
    return rows


def read_baseline_glossary(export_dir: Path) -> list[dict[str, str]]:
    source_rows = read_csv(export_dir / "术语表.csv")
    cached_translations = load_jsonl(export_dir / "翻译缓存" / "术语翻译.jsonl", "术语ID", "统一中文译名")
    rows = []
    for row in source_rows:
        translated = cached_translations.get(row["术语ID"], row.get("统一中文译名", ""))
        rows.append({**row, "统一中文译名": translated, "备注": "已翻译" if translated else row.get("备注", "")})
    return rows


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path
    try:
        handle = target.open("w", encoding="utf-8", newline="")
    except PermissionError:
        target = path.with_name(f"{path.stem}_文化修订{path.suffix}")
        print(f"locked_output={path}; fallback_output={target}")
        handle = target.open("w", encoding="utf-8", newline="")
    with handle:
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


def extract_json(raw: str) -> dict[str, object]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(raw[start : end + 1])


def call_api(api_key: str, system_prompt: str, payload: dict[str, object], timeout: int, retries: int) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    request = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        "max_tokens": 8192,
        "response_format": {"type": "json_object"},
    }
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(API_URL, headers=headers, json=request, timeout=timeout)
            if response.status_code in {429, 500, 502, 503, 504}:
                time.sleep(min(60, attempt * attempt * 2))
                continue
            response.raise_for_status()
            return extract_json(response.json()["choices"][0]["message"]["content"])
        except Exception as exc:
            last_error = exc
            time.sleep(min(60, attempt * attempt * 2))
    raise RuntimeError(f"API failed after {retries} retries: {last_error}")


def split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split("；") if item.strip()]


def contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def placeholder_counter(text: str) -> Counter[str]:
    return Counter(PLACEHOLDER_RE.findall(text))


def strict_placeholder_safe(english: str, translation: str) -> bool:
    return placeholder_counter(english) == placeholder_counter(translation)


def is_nord_royal_context(english: str) -> bool:
    lowered = english.lower()
    if "king of the nordvyg" in lowered or "queen of the nordvyg" in lowered:
        return True
    if any(marker in lowered for marker in NON_NORD_ROYAL_MARKERS):
        return False
    return any(marker in lowered for marker in NORD_ROYAL_MARKERS)


def restore_non_nord_royal_terms(translation: str, english: str) -> str:
    if is_nord_royal_context(english):
        return translation
    lowered = english.lower()
    result = translation
    result = result.replace("至高女科农格", "至高女王")
    result = result.replace("高女科农格", "至高女王")
    result = result.replace("至高科农格", "至高王")
    result = result.replace("科农格王国", "王国")
    result = result.replace("科农格宫", "王宫")
    if "lord" in lowered and "king" not in lowered and "queen" not in lowered:
        result = result.replace("女科农格", "女领主")
        result = result.replace("科农格", "领主")
    else:
        result = result.replace("女科农格", "女王")
        result = result.replace("科农格", "国王")
    return result


def apply_known_replacements(translation: str, english: str) -> str:
    result = restore_non_nord_royal_terms(translation, english)
    english_lower = english.lower()
    for old, new in ZH_REPLACEMENTS:
        if old in result:
            if old in {"国王", "女王", "新王", "老国王", "一国之君"} and not is_nord_royal_context(english):
                continue
            if old in {"领主", "领主们", "女领主"} and "jarl" not in english_lower:
                continue
            if old == "民兵":
                if "fyrd" not in english_lower:
                    continue
                result = re.sub(r"(?<!菲尔德)民兵", new, result)
                continue
            if old in {"护卫"} and "huscarl" not in english_lower:
                continue
            if old in {"狂战士"} and "berserk" not in english_lower:
                continue
            result = result.replace(old, new)
    while "菲尔德菲尔德" in result:
        result = result.replace("菲尔德菲尔德", "菲尔德")
    return result


def candidate_special_names(glossary_rows: list[dict[str, str]], limit: int = 900) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    allowed_types = {"角色人物", "国家文化家族", "定居点文本", "舰船航海", "任务剧情", "对话文本"}
    blocked_words = {
        "Bow",
        "Animal",
        "Queen",
        "King",
        "Fire Ballista",
        "Accuracy Training",
        "Exit Story Mode",
    }
    for row in glossary_rows:
        term = row["英文术语"].strip()
        if not term or term in seen or term in blocked_words:
            continue
        term_type = row["术语类型"]
        if term_type not in allowed_types:
            continue
        if len(term) > 80 or re.search(r"[.!?]", term):
            continue
        if not re.search(r"[A-Z]", term):
            continue
        if re.search(r"\b(Guard|Blade|Grip|Pommel|Spear|Sword|Armor|Helmet|Boots|Gloves|Canopy|Pavilion|Training|Upgrade)\b", term):
            if term_type not in {"角色人物", "国家文化家族", "定居点文本"}:
                continue
        candidates.append(row)
        seen.add(term)
        if len(candidates) >= limit:
            break
    return candidates


def build_cultural_term_table(glossary_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    current_by_term = {row["英文术语"]: row.get("统一中文译名", "") for row in glossary_rows}
    rows: list[dict[str, str]] = []
    for english, culture, kind, current, unified, rule, example in FIXED_CULTURAL_TERMS:
        rows.append(
            {
                "英文术语": english,
                "文化": culture,
                "类型": kind,
                "当前译名": current_by_term.get(english, current),
                "统一译名": unified,
                "使用规则": rule,
                "示例": example,
            }
        )
    return rows


def build_fixed_special_name_table(glossary_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    current_by_term = {row["英文术语"]: row.get("统一中文译名", "") for row in glossary_rows}
    rows: list[dict[str, str]] = []
    for english, kind, current, unified, rule, source in FIXED_SPECIAL_NAMES:
        rows.append(
            {
                "英文专名": english,
                "类型": kind,
                "当前译名": current_by_term.get(english, current),
                "统一音译": unified,
                "使用规则": rule,
                "来源": source,
            }
        )
    return rows


def ai_transliterate_special_names(
    candidates: list[dict[str, str]],
    existing: list[dict[str, str]],
    export_dir: Path,
    args: argparse.Namespace,
    api_key: str,
) -> list[dict[str, str]]:
    cache_path = export_dir / "翻译缓存" / "专名音译.jsonl"
    cached = load_jsonl(cache_path, "英文专名", "统一音译")
    existing_names = {row["英文专名"] for row in existing}
    pending = [row for row in candidates if row["英文术语"] not in existing_names and row["英文术语"] not in cached]
    system_prompt = (
        "你是游戏汉化专名音译编辑。为《骑马与砍杀2：霸主》战帆相关专名生成简体中文音译。"
        "人物、地点、家族、组织、船名、特殊称号都以音译为主。"
        "船名可加“号”，组织可加“团”，家族可加“氏族”，不要意译含义。"
        "只输出JSON对象：{\"names\":[{\"en\":\"...\",\"zh\":\"...\",\"type\":\"...\",\"rule\":\"...\"}]}"
    )
    for start in range(0, len(pending), args.name_batch_size):
        batch = pending[start : start + args.name_batch_size]
        payload = {
            "task": "transliterate_special_names",
            "items": [
                {
                    "en": row["英文术语"],
                    "type": row["术语类型"],
                    "current_zh": row.get("统一中文译名", ""),
                    "categories": row.get("分类列表", ""),
                }
                for row in batch
            ],
        }
        result = call_api(api_key, system_prompt, payload, args.timeout, args.retries)
        names = result.get("names", [])
        if not isinstance(names, list):
            raise RuntimeError("missing names array")
        by_en = {str(item.get("en", "")): item for item in names if isinstance(item, dict)}
        for row in batch:
            item = by_en.get(row["英文术语"])
            if not item:
                continue
            zh = str(item.get("zh", "")).strip()
            if not zh:
                continue
            cached[row["英文术语"]] = zh
            append_jsonl(
                cache_path,
                {
                    "英文专名": row["英文术语"],
                    "统一音译": zh,
                    "类型": str(item.get("type", row["术语类型"])),
                    "使用规则": str(item.get("rule", "AI音译")),
                },
            )
        print(f"name_transliteration_progress={len(cached)}/{len(candidates)}")
        time.sleep(args.sleep)

    rows = list(existing)
    existing_names = {row["英文专名"] for row in rows}
    for row in candidates:
        term = row["英文术语"]
        if term in existing_names:
            continue
        zh = cached.get(term)
        if not zh:
            continue
        rows.append(
            {
                "英文专名": term,
                "类型": row["术语类型"],
                "当前译名": row.get("统一中文译名", ""),
                "统一音译": zh,
                "使用规则": "AI音译，保留文化专名。",
                "来源": "术语表候选",
            }
        )
        existing_names.add(term)
    return rows


def relevant_terms_for_row(english: str, cultural_rows: list[dict[str, str]], special_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    terms: list[dict[str, str]] = []
    lower = english.lower()
    for row in cultural_rows:
        term = row["英文术语"]
        if term in {"king", "queen"} and not is_nord_royal_context(english):
            continue
        if term.lower() in lower:
            terms.append({"en": term, "zh": row["统一译名"], "type": row["类型"]})
    for row in special_rows:
        term = row["英文专名"]
        if term.lower() in lower:
            terms.append({"en": term, "zh": row["统一音译"], "type": row["类型"]})
    return terms


def row_needs_revision(row: dict[str, str], cultural_rows: list[dict[str, str]], special_rows: list[dict[str, str]]) -> bool:
    if relevant_terms_for_row(row["英文原文"], cultural_rows, special_rows):
        return True
    zh = row["中文译文"]
    return any(old in zh for old, _ in ZH_REPLACEMENTS)


def revise_rows(
    dictionary_rows: list[dict[str, str]],
    cultural_rows: list[dict[str, str]],
    special_rows: list[dict[str, str]],
    export_dir: Path,
    args: argparse.Namespace,
    api_key: str,
) -> list[dict[str, str]]:
    cache_path = export_dir / "翻译缓存" / "文化专名修订.jsonl"
    cached = load_jsonl(cache_path, "词条ID", "中文译文")
    target_ids = {row["词条ID"] for row in dictionary_rows if row_needs_revision(row, cultural_rows, special_rows)}
    candidates = [row for row in dictionary_rows if row["词条ID"] in target_ids and row["词条ID"] not in cached]
    system_prompt = (
        "你是游戏汉化审校编辑。任务是在现有中文译文上做局部修订，只改文化称呼和专名音译。"
        "不要重写普通内容，不要扩写，不要改变句意。"
        "文化称呼必须按给定术语表执行，不要把 jarl、huscarl、fyrdman 等译成通用领主、护卫、民兵。"
        "专名以音译为主。必须保留所有 ⟦P#⟧ 占位符。"
        "只输出JSON对象：{\"revisions\":[{\"id\":\"...\",\"zh\":\"...\"}]}"
    )
    for start in range(0, len(candidates), args.revision_batch_size):
        batch = candidates[start : start + args.revision_batch_size]
        items = []
        placeholder_by_id: dict[str, list[str]] = {}
        for row in batch:
            masked_en, placeholders = base.mask_placeholders(row["英文原文"])
            masked_zh, _ = base.mask_placeholders(apply_known_replacements(row["中文译文"], row["英文原文"]))
            placeholder_by_id[row["词条ID"]] = placeholders
            items.append(
                {
                    "id": row["词条ID"],
                    "en": masked_en,
                    "current_zh": masked_zh,
                    "terms": relevant_terms_for_row(row["英文原文"], cultural_rows, special_rows),
                    "categories": row["分类列表"],
                }
            )
        payload = {"task": "revise_cultural_terms_only", "items": items}
        result = call_api(api_key, system_prompt, payload, args.timeout, args.retries)
        revisions = result.get("revisions", [])
        if not isinstance(revisions, list):
            raise RuntimeError("missing revisions array")
        by_id = {str(item.get("id", "")): item for item in revisions if isinstance(item, dict)}
        for row in batch:
            item = by_id.get(row["词条ID"])
            if not item:
                revised = apply_known_replacements(row["中文译文"], row["英文原文"])
            else:
                revised = str(item.get("zh", "")).strip() or apply_known_replacements(row["中文译文"], row["英文原文"])
            revised = base.unmask_placeholders(revised, placeholder_by_id[row["词条ID"]])
            if not base.placeholder_safe(row["英文原文"], revised):
                revised = apply_known_replacements(row["中文译文"], row["英文原文"])
            cached[row["词条ID"]] = revised
            append_jsonl(cache_path, {"词条ID": row["词条ID"], "英文原文": row["英文原文"], "中文译文": revised})
        print(f"revision_progress={len(cached)}/{len(candidates)}")
        time.sleep(args.sleep)

    output_rows = []
    for row in dictionary_rows:
        revised = cached.get(row["词条ID"], row["中文译文"]) if row["词条ID"] in target_ids else row["中文译文"]
        revised = apply_known_replacements(revised, row["英文原文"])
        output_rows.append({**row, "中文译文": revised, "翻译状态": "已翻译", "备注": "文化称呼与专名音译修订"})
    return output_rows


def update_glossary(glossary_rows: list[dict[str, str]], cultural_rows: list[dict[str, str]], special_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    cultural_map = {row["英文术语"]: row["统一译名"] for row in cultural_rows}
    special_map = {row["英文专名"]: row["统一音译"] for row in special_rows}
    output = []
    for row in glossary_rows:
        term = row["英文术语"]
        zh = row["统一中文译名"]
        if term == "king":
            zh = "国王"
        elif term == "queen":
            zh = "女王"
        elif term in cultural_map:
            zh = cultural_map[term]
        elif term in special_map:
            zh = special_map[term]
        else:
            zh = apply_known_replacements(zh, term)
        output.append({**row, "统一中文译名": zh, "备注": "文化称呼与专名音译修订"})
    return output


def repair_placeholder_mismatches(
    dictionary_rows: list[dict[str, str]],
    export_dir: Path,
    args: argparse.Namespace,
    api_key: str,
) -> list[dict[str, str]]:
    cache_path = export_dir / "翻译缓存" / "占位符精修.jsonl"
    cached = load_jsonl(cache_path, "词条ID", "中文译文")
    candidates = [
        row
        for row in dictionary_rows
        if row["词条ID"] not in cached and not strict_placeholder_safe(row["英文原文"], row["中文译文"])
        and row["词条ID"] not in PLACEHOLDER_REPAIR_OVERRIDES
    ]
    system_prompt = (
        "你是游戏汉化占位符校对编辑。任务是在现有中文译文上做最小修订，使中文译文包含英文原文中每一个 {...} 占位符，"
        "占位符文本、数量必须完全一致。不要改写普通内容，不要删除任何 {...}，不要新增英文原文中不存在的 {...}。"
        "性别条件片段也必须保留，例如 {?X}她{?}他{\\?}。只输出JSON对象："
        "{\"revisions\":[{\"id\":\"...\",\"zh\":\"...\"}]}"
    )
    for start in range(0, len(candidates), args.revision_batch_size):
        batch = candidates[start : start + args.revision_batch_size]
        payload = {
            "task": "repair_placeholder_instances",
            "items": [
                {
                    "id": row["词条ID"],
                    "en": row["英文原文"],
                    "current_zh": row["中文译文"],
                    "required_placeholders": PLACEHOLDER_RE.findall(row["英文原文"]),
                    "current_placeholders": PLACEHOLDER_RE.findall(row["中文译文"]),
                }
                for row in batch
            ],
        }
        result = call_api(api_key, system_prompt, payload, args.timeout, args.retries)
        revisions = result.get("revisions", [])
        if not isinstance(revisions, list):
            raise RuntimeError("missing revisions array")
        by_id = {str(item.get("id", "")): item for item in revisions if isinstance(item, dict)}
        for row in batch:
            item = by_id.get(row["词条ID"])
            repaired = str(item.get("zh", "")).strip() if item else row["中文译文"]
            repaired = apply_known_replacements(repaired, row["英文原文"])
            cached[row["词条ID"]] = repaired
            append_jsonl(cache_path, {"词条ID": row["词条ID"], "英文原文": row["英文原文"], "中文译文": repaired})
        print(f"placeholder_repair_progress={len(cached)}/{len(candidates)}")
        time.sleep(args.sleep)

    output_rows = []
    for row in dictionary_rows:
        translation = PLACEHOLDER_REPAIR_OVERRIDES.get(row["词条ID"], cached.get(row["词条ID"], row["中文译文"]))
        translation = apply_known_replacements(translation, row["英文原文"])
        output_rows.append({**row, "中文译文": translation})
    return output_rows


def write_validation(export_dir: Path, errors: list[str], revised_rows: list[dict[str, str]], cultural_rows: list[dict[str, str]], special_rows: list[dict[str, str]]) -> None:
    lines = [
        "# 文化称呼与专名音译修订验证报告",
        "",
        f"词典总行数：{len(revised_rows)}",
        f"文化称呼表条目：{len(cultural_rows)}",
        f"专名音译表条目：{len(special_rows)}",
        f"中文译文空值：{sum(1 for row in revised_rows if not row['中文译文'])}",
        f"占位符错误：{sum(1 for row in revised_rows if not strict_placeholder_safe(row['英文原文'], row['中文译文']))}",
        f"验证错误数：{len(errors)}",
        "",
        "验证结论：通过" if not errors else "验证结论：未通过",
    ]
    if errors:
        lines.extend(["", "错误："])
        lines.extend(f"- {error}" for error in errors)
    (export_dir / "文化称呼与专名音译修订验证报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def strict_placeholder_errors(revised_rows: list[dict[str, str]]) -> list[str]:
    offenders = [row["词条ID"] for row in revised_rows if not strict_placeholder_safe(row["英文原文"], row["中文译文"])]
    if offenders:
        return [f"严格占位符不一致: {offenders[:30]}"]
    return []


def extra_validations(revised_rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    checks = [
        ("jarl", "领主"),
        ("king of the Nordvyg", "诺德维格之王"),
        ("queen of the Nordvyg", "诺德维格女王"),
        ("Fyrdman", "民兵"),
        ("Huscarl", "护卫"),
        ("Drengr", "战士"),
        ("Berserkir", "狂战士"),
        ("Golden Wasp", "金蜂号"),
        ("Wave-Breaker", "破浪"),
        ("Sea Hounds", "海猎犬"),
        ("Sea Hounds", "海狼"),
        ("Sea Hounds", "海犬"),
    ]
    for en, forbidden in checks:
        offenders = [row["词条ID"] for row in revised_rows if en.lower() in row["英文原文"].lower() and forbidden in row["中文译文"]]
        if en == "Fyrdman":
            offenders = [
                row["词条ID"]
                for row in revised_rows
                if en.lower() in row["英文原文"].lower()
                and forbidden in row["中文译文"]
                and "菲尔德民兵" not in row["中文译文"]
            ]
        if offenders:
            errors.append(f"{en} 仍含 {forbidden}: {offenders[:5]}")
    repeated_fyrd = [row["词条ID"] for row in revised_rows if "菲尔德菲尔德" in row["中文译文"]]
    if repeated_fyrd:
        errors.append(f"菲尔德重复替换: {repeated_fyrd[:5]}")
    wrong_high_king = [
        row["词条ID"]
        for row in revised_rows
        if ("high king" in row["英文原文"].lower() or "high queen" in row["英文原文"].lower())
        and "科农格" in row["中文译文"]
        and "nordvyg" not in row["英文原文"].lower()
    ]
    if wrong_high_king:
        errors.append(f"非诺德 High King/Queen 误用科农格: {wrong_high_king[:5]}")
    non_nord_konungr = [
        row["词条ID"]
        for row in revised_rows
        if "科农格" in row["中文译文"] and not is_nord_royal_context(row["英文原文"])
    ]
    if non_nord_konungr:
        errors.append(f"非诺德语境误用科农格: {non_nord_konungr[:10]}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name-batch-size", type=int, default=60)
    parser.add_argument("--revision-batch-size", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--sleep", type=float, default=0.15)
    args = parser.parse_args()

    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"missing {API_KEY_ENV}")

    modules_root = Path(__file__).resolve().parent
    export_dir = modules_root / EXPORT_DIR_NAME
    glossary_rows = read_baseline_glossary(export_dir)
    dictionary_rows = read_baseline_dictionary(export_dir)

    cultural_rows = build_cultural_term_table(glossary_rows)
    fixed_special_rows = build_fixed_special_name_table(glossary_rows)
    special_candidates = candidate_special_names(glossary_rows)
    special_rows = ai_transliterate_special_names(special_candidates, fixed_special_rows, export_dir, args, api_key)

    revised_glossary = update_glossary(glossary_rows, cultural_rows, special_rows)
    revised_dictionary = revise_rows(dictionary_rows, cultural_rows, special_rows, export_dir, args, api_key)
    revised_dictionary = repair_placeholder_mismatches(revised_dictionary, export_dir, args, api_key)

    write_csv(export_dir / "文化称呼表.csv", cultural_rows, CULTURAL_TERM_COLUMNS)
    write_csv(export_dir / "专名音译表.csv", special_rows, SPECIAL_NAME_COLUMNS)
    write_csv(export_dir / "术语表_已翻译.csv", revised_glossary, base.GLOSSARY_COLUMNS)
    write_csv(export_dir / "全量翻译词典_已翻译.csv", revised_dictionary, base.DICTIONARY_COLUMNS)
    write_text_tables(export_dir, revised_dictionary)
    base.build_chinese_module(modules_root, export_dir, revised_dictionary)
    errors = base.validate_outputs(modules_root, export_dir, revised_dictionary)
    errors.extend(strict_placeholder_errors(revised_dictionary))
    errors.extend(extra_validations(revised_dictionary))
    base.write_validation_report(export_dir, errors, revised_dictionary)
    write_validation(export_dir, errors, revised_dictionary, cultural_rows, special_rows)

    print(f"cultural_terms={len(cultural_rows)}")
    print(f"special_names={len(special_rows)}")
    print(f"dictionary_rows={len(revised_dictionary)}")
    print(f"validation_errors={len(errors)}")
    print(f"export_dir={export_dir}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
