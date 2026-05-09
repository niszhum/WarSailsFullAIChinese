# WarSailsFullAIChinese

骑马与砍杀 2：霸主 战帆 DLC 全量 AI 简体中文替换翻译 Mod。

## 内容

- 覆盖 Native、SandBoxCore、SandBox、StoryMode、CustomBattle、BirthAndDeath、Multiplayer、NavalDLC 的当前有效英文文本。
- 独立 Mod 形式加载语言 XML，不覆盖官方模块文件。
- 舰船、海战、港口、家族、组织、船名、角色称号按统一术语修订。
- 文化相关称呼优先使用文化称呼，例如 `jarl -> 雅尔`、`king of the Nordvyg -> 诺德维格科农格`、`Sea Hounds -> 西霍恩德团`。

## 安装

1. 将本目录复制到游戏目录的 `Modules` 下。
2. 最终路径应为：

```text
Mount & Blade II Bannerlord/Modules/WarSailsFullAIChinese/SubModule.xml
```

3. 在启动器中启用 `战帆全量AI汉化`。
4. 需要游戏本体。战帆 DLC 内容需要安装并启用 `NavalDLC`。

## 目录

```text
SubModule.xml
ModuleData/Languages/CNs/*.xml
tools/
translation-data/
docs/
```

- `ModuleData/Languages/CNs`：游戏加载用简体中文语言 XML。
- `tools`：英文提取、AI 翻译、文化称呼修订脚本。
- `translation-data`：最终词典、带译文文本表、术语表、文化称呼表、专名音译表。
- `docs`：验证报告。

## 验证结果

- 全量词典：23,591 行。
- 当前有效文本：24,321 行。
- 战帆 DLC 文本：3,669 行。
- 语言 XML：107 个文件，22,713 条字符串。
- 中文译文空值：0。
- 严格 `{...}` 占位符错误：0。
- XML 解析错误：0。
- 官方模块目录写入变更：0。

## 说明

本仓库不包含官方游戏资源文件。仓库中的语言 XML 和 CSV 为本地生成的汉化交付物。

翻译由 AI 全新生成，未使用官方中文译文预填。专名以音译为主，文化称呼按 `translation-data/文化称呼表.csv` 和 `translation-data/专名音译表.csv` 统一。
