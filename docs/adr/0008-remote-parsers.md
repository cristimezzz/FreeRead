# ADR-0008：可选的远程解析服务（自部署 / 云端 MinerU 与 Docling）

- 状态：**已接受**
- 日期：2026-10-20
- 修订：[ADR-0003](0003-pluggable-parser.md) 第 5 点（"文档不离开本机"由硬性保证改为默认行为）

## 背景

高质量解析要么需要本机装 MinerU / Docling 的独立环境，要么就只能用快速模式。没有 GPU、装不上重型引擎，或者团队里已经有现成的解析服务时，用户无法得到高质量解析（路线图"用户无 GPU → 可选云解析"）。

MinerU 4.x 的 v1 REST 协议对本机 `mineru-api` 和云端 `https://mineru.net/api` 是同一套接口：上传 → 提交任务 → 轮询 → 下载产物。产物 `middle_json` 与本机 `doc_analyze` 的输出同为 docvortex.middle 2.0。docling-serve 的 v1 API 返回的 `json_content` 就是 `DoclingDocument.export_to_dict()`。也就是说，现有 Normalizer 可以原样复用。

## 备选方案

1. **按引擎选运行位置**：引擎名仍是 `mineru` / `docling`，每个引擎可以设为"本机"或"API 服务"（Base URL + 可选 API Key）。
2. 新增独立的引擎名（如 `mineru_api`），与本机引擎并列出现在引擎列表里。

## 决定

选方案 1。

1. **设置** `settings.parsers.{mineru,docling}`：
   - `mode`：`local` / `api`
   - `base_url`
   - `tier`：仅 MinerU 使用，默认 `basic`，与本机 `effort=medium` 同档
   - `consented_url`：用户确认过的公网地址
   
   API Key 存在系统钥匙串，ID 为 `parser-<engine>`。LLM provider 不能使用 `parser-` 前缀的 ID。
2. **实现**：
   - `infra/parsers/mineru_api.py`、`docling_api.py` 实现 `Parser` 接口，只依赖 httpx，不 import 引擎包。
   - 产物写到 `raw/<engine>/`，与本机引擎相同：`middle.json` 或 `docling.json`，加上 `engine.json`（`transport: "api"`）。
   - 质量等级（rank）、Normalizer 和重新规范化流程都不变。
   - 图表图片不下载，仍由解析任务按 bbox 从 PDF 截取。
3. **隐私**：
   - 默认仍是本机解析。
   - 指向本机、局域网或链路本地地址时，PDF 不出本地网络，不需要确认。
   - 指向公网地址时，用户必须先在设置里点"允许上传"，引擎才算可用。改了 Base URL，之前的确认就作废（`consented_url != base_url`）。
   - 未确认时，自动升级链会跳过该引擎，手动触发则返回 409，不会悄悄上传。
   - FreeRead 本身不向解析服务发送遥测。
4. **版本要求**：远程 MinerU 必须 ≥ 4.0。`middle_json` 缺少 `extensions.docvortex_layout` 时直接报"服务端版本过旧"，不兼容 3.x 的 `pdf_info` 格式。
5. **同机优化**：服务地址是 loopback，并且服务声明支持 `local` 来源（`mineru-api --allow-local-source`）时，直接传本地路径，不上传。

## 后果

- 正面：
  - 没有 GPU 的用户也能用 MinerU / Docling。
  - 团队可以共用一台解析服务器。
  - 云端 MinerU 可以选 `standard` / `advanced` 档位（VLM）。
  - 上层功能和 IR 完全不受影响。
- 负面：
  - 选了公网服务后，PDF 原文会离开本机（需要用户明确同意）。
  - 远程服务的版本不受 FreeRead 控制，Normalizer 可能遇到没测过的输出。
  - `parse_hq` 仍是全局并发 1，远程解析不占本机 GPU，但也不能并行。
- 跟进：
  - `standard` / `advanced` 档位的输出需要用评测集回归（`scripts/m0_report.py`）。
  - 远程引擎允许更高的并发。
  - docling-serve 没有取消接口，任务取消后服务端仍会跑完。
