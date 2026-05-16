# 人物标签来源名单

把人工整理或导出的来源名单放到这个目录下，然后执行：

```bash
make person-registry-refresh
```

支持的 CSV 列：

```text
name,tag_type,aliases,source_links,matched_affiliations,openalex_author_ids,orcid_ids,dblp_author_ids,known_institutions,note
```

其中列表类型字段使用 `;` 分隔：

```csv
name,tag_type,aliases,source_links,matched_affiliations,openalex_author_ids,orcid_ids,dblp_author_ids,known_institutions,note
Grace Hopper,ieee_fellow,G. Hopper,https://example.com/grace,,https://openalex.org/A123;https://openalex.org/A456,orcid:0000-0001-2345-6789,,Yale University;Harvard University,"IEEE Fellow source"
Alan Turing,acm_fellow,A. Turing,https://example.com/turing,Princeton University,,,turing/T/Alan,Princeton University,"ACM Fellow source"
```

`openalex_author_ids`、`orcid_ids`、`dblp_author_ids`、`known_institutions` 是可选的补强字段，供自动人物匹配裁决使用。执行 `make person-registry-refresh` 时，这些字段会被合并并保留下来。

你也可以把浏览器里复制出来的 ACM Fellows 表格直接保存成 `.txt` 或 `.tsv` 文件。导入脚本能识别类似下面这样的行：

```text
Adar, Eytan	ACM Fellows	2025	North America	Digital Library
Bengio, Yoshua	ACM Fellows	2023	North America	Digital Library
```

比如可以保存成：

```text
data/reference/source_lists/acm_fellows_paste.txt
```

然后执行 `make person-registry-refresh`。

IEEE Computer Society Fellow 的届次页面也可以同样处理。把复制下来的页面文本保存成类似：

```text
data/reference/source_lists/ieee_cs_fellows_2026.txt
```

像下面这样的行会被导入为 `ieee_fellow`：

```text
IEEE Computer Society Announces 2026 Class of Fellows
Tamim Asfour - for contributions to humanoid robotics and robot learning
Anupam Chattopadhyay for contributions to embedded systems security
```

也可以尝试直接在线抓取 IEEE CS 页面：

```bash
make person-registry-refresh PERSON_REGISTRY_FETCH_IEEE_CS=1
```

如果站点返回 HTTP 403，就退回到“手动复制页面文本到 `.txt` 文件”的方式。

当 `computer.org` 无法访问时，可以把 Wikipedia 上的 `List of fellows of IEEE Computer Society` 作为次级来源。复制出来的表格如果长这样，也会被导入为 `ieee_fellow`：

```text
Year	Fellow	Citation
2020	Hussein Abbass	For contributions to evolutionary learning and optimization
2023	Gail-Joon Ahn	For development of applications of information and systems security
```

对应的在线兜底抓取方式是：

```bash
make person-registry-refresh PERSON_REGISTRY_FETCH_IEEE_CS_WIKIPEDIA=1
```

仓库里也已经包含了一份生成好的次级来源快照：

```text
data/reference/source_lists/ieee_computer_society_fellows_wikipedia.json
data/reference/source_lists/ieee_cross_field_fellows_wikipedia.json
```

只有当源页面发生变化时才需要重新生成。只要官方 IEEE / Computer Society 来源能访问，优先使用官方来源文件。

当前 cross-field IEEE 快照覆盖的是当时能正常访问、且结构可解析的 Wikipedia 名单页面，包括：

- Communications Society
- Circuits and Systems Society
- Computational Intelligence Society
- Control Systems Society

对于 Wikipedia 红链页面，或者结构不是标准表格的列表页，当前会跳过，等后续拿到官方来源或更容易解析的页面后再补。

CAS / CAE 信息领域院士目前也维护为官方来源快照：

```text
data/reference/source_lists/cas_information_technology_academicians_official.json
data/reference/source_lists/cae_information_electronics_academicians_official.json
```

完整的 CAS / CAE 院士和外籍院士名单则维护为独立的官方来源快照：

```text
data/reference/source_lists/cas_all_academicians_official.json
data/reference/source_lists/cas_foreign_academicians_official.json
data/reference/source_lists/cas_deceased_academicians_official.json
data/reference/source_lists/cas_deceased_foreign_academicians_official.json
data/reference/source_lists/cae_all_academicians_official.json
data/reference/source_lists/cae_foreign_academicians_official.json
data/reference/source_lists/cae_deceased_academicians_official.json
data/reference/source_lists/cae_deceased_foreign_academicians_official.json
```

当前官方数量检查点：

- CAS 全体院士：892，来自当前全体院士详情页链接集合
- CAS 已故院士：738，来自已故院士详情页链接集合
- CAS 已故外籍院士：42，若官方名称里括号含英文，则保留英文名作为 `name`
- CAE 全体院士：981，按 CAE 详情页 URL 去重；工程管理跨学部展示合并计数，不重复算
- CAE 外籍院士：146，来自 CAE 外籍院士名单
- CAE 已故院士：380，来自 CAE 已故院士表格
- CAE 已故外籍院士：24，来自 CAE 已故外籍院士表格

为了匹配 DBLP / OpenAlex / Scopus 作者名，中国科学院、中国工程院相关条目会自动生成拼音别名。外籍院士条目则优先使用英文名作为 `name`，如有中文官方名则放在 `aliases` 里。

支持的 JSON 格式：

```json
{
  "items": [
    {
      "name": "Grace Hopper",
      "tag_type": "ieee_fellow",
      "aliases": ["G. Hopper"],
      "source_links": ["https://example.com/grace"],
      "matched_affiliations": [],
      "openalex_author_ids": ["https://openalex.org/A123"],
      "orcid_ids": ["orcid:0000-0001-2345-6789"],
      "dblp_author_ids": [],
      "known_institutions": ["Yale University"],
      "note": "IEEE Fellow source"
    }
  ]
}
```

或者也可以直接使用同样对象结构组成的原始列表。

支持的 `tag_type` 取值：

- `acm_fellow`
- `ieee_fellow`
- `cas_academician`
- `cae_academician`
- `top_school`

刷新脚本只负责生成和更新 registry 条目；是否最终成为有效命中，仍由后续的自动匹配裁决逻辑决定。

如果你已经有对比结果包，想保守地做 OpenAlex 身份补强，可以这样用：

```bash
python3 scripts/enrich_person_tag_registry_openalex.py \
  --registry-path data/reference/person_tag_registry.json \
  --review-zip /path/to/author_level_analysis_outputs.zip \
  --dry-run
```

去掉 `--dry-run` 后，脚本只会把高置信命中写回。这个 enrichment 门槛是故意设得很严的：宁可跳过常见重名，也不猜一个看起来像的 ID。

无论是否命中，脚本都会默认额外写出一份 CSV 审计文件：

```text
data/reference/openalex_enrichment_audit.csv
```

里面会保留每条处理记录的：

- `decision`：是否写回
- `confidence_percent`：结合分数和第一名/第二名分差后的可采信程度
- `score_percent` / `top_score_percent`
- `top_openalex_id`
- `runner_up_score`
- `reason`

这样即使没有自动命中，也能把结果留给后续复查。

如果你希望把每个名字对应的多个候选 OpenAlex ID 一并导出来，方便后续交给其他 AI 二次判断，可以再加：

```bash
--candidate-report-csv /path/to/openalex_candidate_queue.csv \
--candidate-limit-per-name 5
```

这会额外生成一个候选集合 CSV，每行一个候选人，包含：

- 原始名字
- `rank`
- `openalex_id`
- `display_name`
- `orcid`
- `institutions`
- `score` / `score_percent`
- `reasons`

如果已经让 AI 对 OpenAlex audit/candidates 做过二次判定，并且还剩大量 unresolved，可以继续用交叉验证脚本引入 DBLP、Scopus 或引用作者 metadata 证据：

```bash
python3 scripts/cross_validate_openalex_candidates.py \
  --resolution-zip /mnt/d/Desktop/openalex_ai_resolution_2600.zip \
  --candidates-csv /mnt/c/Users/withe/Desktop/openalex_candidates_ieee_merged_2600.csv \
  --raw-citing-authors-csv /mnt/c/Users/withe/Desktop/raw_citing_authors.csv \
  --use-dblp \
  --use-scopus \
  --output-csv /mnt/c/Users/withe/Desktop/openalex_cross_validation_ieee_2600.csv \
  --summary-csv /mnt/c/Users/withe/Desktop/openalex_cross_validation_summary_ieee_2600.csv
```

其中：

- `--raw-citing-authors-csv` 可选，来自学者页的 `Export Raw Citing Authors CSV`
- `--use-dblp` 会查询 DBLP 作者搜索接口，适合 CS/IEEE 名字辅助判断
- `--use-scopus` 会查询 Elsevier Scopus Author Search，需要配置 `ELSEVIER_API_KEY`
- 输出文件仍然不会写回 registry，只是生成候选级证据表，便于后续 AI 或规则继续筛选

如果想直接从 registry 里批量补外部 ID，可以这样跑：

```bash
export OPENALEX_API_KEY="你的_openalex_api_key"

python3 scripts/enrich_person_tag_registry_openalex.py \
  --registry-path data/reference/person_tag_registry.json \
  --all-missing-external-ids \
  --tag-type ieee_fellow \
  --offset 200 \
  --limit 20 \
  --dry-run
```

这个模式会直接遍历 registry 里的名字，用 OpenAlex 按名字查询，并且只在高置信时写回结果。它的目标是提高吞吐量，但依然坚持“宁缺毋滥”，优先避免写入错误 ID。

建议在批量跑之前先设置 `OPENALEX_API_KEY`，或者显式传 `--api-key`。截至 2026-05，OpenAlex 对无 key 请求的额度非常低，更容易触发 `429 Too Many Requests`。

其中：

- `--offset` 用来跳过前面已经跑过的目标，适合续跑下一批
- `--limit` 用来限制本次处理条数

例如：

- 第 1 批：`--offset 0 --limit 200`
- 第 2 批：`--offset 200 --limit 200`
- 第 3 批：`--offset 400 --limit 200`
