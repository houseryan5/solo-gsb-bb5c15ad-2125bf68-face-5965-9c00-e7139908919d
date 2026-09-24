# 采访逐字稿校时 API（Transcript Alignment API）

把按时间排序的语音识别字符与人工修订文本做**全局最小编辑代价对齐**，为修订文本中的
**每一个字符**生成毫秒级起止时间轴。删除的字符不输出，新增的字符在相邻已匹配字符
（及录音边界）的空档内**均匀分配**时间。

- 语言 / 框架：Python 3.11 + FastAPI + Uvicorn
- 重复字符结合全局上下文选择匹配位置；同分时优先匹配**较早的原位置**
- 每段时间严格按字符顺序、单调不重叠、且位于 `[0, total_duration_ms]` 内
- 内置健康检查、请求校验与明确的错误信息、OpenAPI 文档

## 单条命令启动

需要本机已安装 Docker（含 Compose 插件）：

```bash
docker compose up --build
```

首次启动时会在容器内自动 `pip install -r requirements.txt`（**依赖在启动时安装**，
见 `entrypoint.sh`），随后启动 Uvicorn。停止用 `Ctrl+C`，后台运行加 `-d`。

## 服务地址与端口

- 默认监听：`http://0.0.0.0:8000`
- 健康检查：`GET http://localhost:8000/health`（`GET /` 等价）
- 校时接口：`POST http://localhost:8000/align`
- 交互式文档：`http://localhost:8000/docs`（Swagger UI）
- OpenAPI Schema：`http://localhost:8000/openapi.json`

## 必要配置

通过环境变量或 Compose 同目录下的 `.env` 文件覆盖（均为可选项）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `8000` | 宿主机映射端口（容器内固定 8000），如 `PORT=9000 docker compose up` |
| `MAX_CHARS_PER_SIDE` | `8000` | 单侧文本最大字符数（识别侧 / 修订侧分别计算） |
| `MAX_ALIGNMENT_CELLS` | `10000000` | DP 规模上限 `(识别字数+1)×(修订字数+1)`，超出返回 413 |

示例 `.env`：

```env
PORT=9000
MAX_CHARS_PER_SIDE=12000
MAX_ALIGNMENT_CELLS=20000000
```

> DP 使用紧凑的 16 位整型矩阵，1000 万单元约占 20 MB 内存。

## 请求

`POST /align`，`Content-Type: application/json`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `chars` | 数组 | 按开始时间**升序**排列的识别字符，每项含 `char` / `start_ms` / `end_ms` |
| `total_duration_ms` | 整数 ≥ 0 | 录音总时长（毫秒） |
| `revised_text` | 字符串 | 人工修订后的完整文本，逐字符（含空格、标点、换行）对齐 |

`chars[]` 中每一项：

| 字段 | 约束 |
| --- | --- |
| `char` | **恰好 1 个** Unicode 字符 |
| `start_ms` | 整数 ≥ 0 |
| `end_ms` | 整数 ≥ 0，且 `end_ms ≥ start_ms`、`end_ms ≤ total_duration_ms` |

相邻字符还必须满足 `start_ms` 不回退、区间不重叠（首尾相接允许）。

### 请求示例

```bash
curl -X POST http://localhost:8000/align \
  -H 'Content-Type: application/json' \
  -d '{
    "total_duration_ms": 1000,
    "chars": [
      {"char": "嗯", "start_ms": 0,   "end_ms": 120},
      {"char": "我", "start_ms": 120, "end_ms": 300},
      {"char": "们", "start_ms": 300, "end_ms": 480},
      {"char": "在", "start_ms": 480, "end_ms": 620},
      {"char": "开", "start_ms": 620, "end_ms": 760},
      {"char": "会", "start_ms": 760, "end_ms": 900}
    ],
    "revised_text": "我们在开大会呀"
  }'
```

## 响应

`items` 顺序与 `revised_text` 字符顺序完全一致：

| 字段 | 说明 |
| --- | --- |
| `char` | 修订字符 |
| `start_ms` / `end_ms` | 毫秒级起止时间 |
| `matched` | `true`：与识别原文匹配，沿用其时间；`false`：人工新增字符 |
| `estimated` | `true`：时间由相邻空档均匀推算；`false`：直接采用识别时间 |

新增字符的分配规则：

- 位于两个已匹配字符之间：在 `[前一字符 end_ms, 后一字符 start_ms]` 空档内均匀切分；
- 位于开头：在 `[0, 第一个匹配字符 start_ms]` 内均匀切分；
- 位于结尾：在 `[最后一个匹配字符 end_ms, total_duration_ms]` 内均匀切分；
- 切分后的时间段首尾相接、完全覆盖空档；余数毫秒依次分给靠前的字符；
  空档为 0 时所有新增字符得到零宽时间段。
- 修订文本与原文完全无匹配时，全部字符在 `[0, total_duration_ms]` 内均匀分配。

上例响应节选：`嗯`被删除（不输出）；`大`插入在「开/会」之间的零宽空档得到
`760–760`；`呀`在录音尾部得到 `900–1000`。

## 错误处理

| 状态码 | 场景 | 示例 detail |
| --- | --- | --- |
| 422 | 起止倒置 | `chars[0] ('我') is invalid: end_ms=100 is earlier than start_ms=500` |
| 422 | 超出录音总时长 | `chars[2] ('a') is invalid: end_ms=120 exceeds total_duration_ms=100` |
| 422 | 时间未排序 / 区间重叠 | `... start_ms=80 overlaps the previous char which ends at 120 ...` |
| 422 | 某项不是单字符 / 时间为负 / 缺字段 | Pydantic 校验错误（含字段定位） |
| 413 | 超出 `MAX_CHARS_PER_SIDE` 或 `MAX_ALIGNMENT_CELLS` | `input too long: ...` |

## 对齐算法说明

代价模型（Needleman–Wunsch / LCS 形式的全局对齐）：

- 相同字符对齐（匹配）代价 0；插入（修订新增）、删除（识别被删）代价各 1；
  不允许异字符替换——替换自然表现为「删除 + 插入」。
- DP 求得全局最小代价；再通过后缀 DP 自左向右贪心重建：在总代价最优的前提下
  **能匹配就匹配**，从而保证修订文本依次匹配到的原文字符下标序列字典序最小，
  即「同分优先较早原位置」。随机用例已用枚举全部对齐的暴力算法交叉验证
  （见 `tests/`）。

## 本地开发（不使用 Docker）

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
python -m unittest discover -s tests     # 运行测试
```

## 项目结构

```
app/
  main.py        # FastAPI 路由、错误处理、配置
  aligner.py     # 全局对齐 DP、时间轴生成、时间校验
  schemas.py     # 请求 / 响应模型
tests/           # 单元 + HTTP 集成测试（含随机暴力校验）
Dockerfile
docker-compose.yml
entrypoint.sh    # 启动时安装依赖并拉起服务
requirements.txt
```
