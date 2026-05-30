# 内网共享服务器最小演示部署说明

适用场景：

- 组内内网公共服务器
- 无 sudo
- 多人共享机器
- 以普通用户身份启动和维护
- 不依赖 nginx / docker / root systemd

推荐主路径：

- 用 `tmux` 保活
- 模型服务与 Web 服务分别启动
- 所有可写目录放在自己账号下

---

## 1. 目录约定

下面这些路径都需要你自己有写权限：

- 项目目录：`~/projects/academic_impact_web`
- PDF 下载目录：`~/data/academic_impact_web/downloads`
- 日志目录：`~/logs/academic_impact_web`

初始化：

```bash
mkdir -p ~/data/academic_impact_web/downloads
mkdir -p ~/logs/academic_impact_web
```

---

## 2. 需要你手工修改的值

### 必改 1：`.env`

至少确认这些值：

```env
ACADEMIC_IMPACT_ANALYSIS_MODE=single_model
ACADEMIC_IMPACT_LLM_URL=http://127.0.0.1:18002/v1/chat/completions
ACADEMIC_IMPACT_LLM_MODEL=Qwen3.5-27B-Q4_K_M.gguf
ACADEMIC_IMPACT_LLM_API_KEY=
ACADEMIC_IMPACT_DOWNLOAD_DIR=/home/YOUR_USER/data/academic_impact_web/downloads
ACADEMIC_IMPACT_PDF_LIBRARY_DIRS=/home/YOUR_USER/papers:/home/YOUR_USER/pdf_archive
```

你需要手工改：

- `ACADEMIC_IMPACT_LLM_URL`
- `ACADEMIC_IMPACT_LLM_MODEL`
- `ACADEMIC_IMPACT_LLM_API_KEY`（本地无鉴权模型可留空；API 模型需填写）
- `ACADEMIC_IMPACT_DOWNLOAD_DIR`
- `ACADEMIC_IMPACT_PDF_LIBRARY_DIRS`（可选；让学者影响力分析先扫本地论文库，不用逐篇上传）

### 必改 2：端口

默认建议：

- Web：`18000`
- 模型：`18002`

如果冲突，请换成别的高位端口。

### 必改 3：模型启动命令

本仓库不会替你猜实际模型服务命令。  
你需要把自己的模型启动命令填到：

- `scripts/start_web_demo.sh`

里的 `MODEL_START_CMD`。

---

## 3. 两种绑定方式

### A. 仅本机访问 / SSH 转发

适合你自己演示，最稳妥。

- Web 绑定：`127.0.0.1:18000`
- 模型绑定：`127.0.0.1:18002`

本地转发：

```bash
ssh -L 18000:127.0.0.1:18000 YOUR_USER@SERVER
```

浏览器访问：

```text
http://127.0.0.1:18000
```

### B. 组内其他机器直接访问

适合内部演示。

- Web 绑定：`0.0.0.0:18000`
- 模型绑定：`127.0.0.1:18002`

然后让组内其他机器访问：

```text
http://<服务器内网IP>:18000
```

如果要查内网 IP：

```bash
hostname -I
```

---

## 4. 启动方式

### 先做环境检查

```bash
cd ~/projects/academic_impact_web
bash scripts/check_demo_env.sh
```

### 用 tmux 启动

```bash
cd ~/projects/academic_impact_web
bash scripts/start_web_demo.sh
```

它会：

- 检查端口是否冲突
- 提醒你确认 `.env`
- 启动 `tmux` 会话：
  - `aiw-model`
  - `aiw-web`

### 查看日志

```bash
tail -f ~/logs/academic_impact_web/model.log
tail -f ~/logs/academic_impact_web/web.log
```

### 查看 tmux

```bash
tmux ls
tmux attach -t aiw-web
tmux attach -t aiw-model
```

---

## 5. 演示前最小自检

### 5.1 端口是否被占用

```bash
ss -ltnp | grep 18000
ss -ltnp | grep 18002
```

### 5.2 模型服务是否可连通

```bash
curl http://127.0.0.1:18002/v1/models
make fulltext-check
```

### 5.3 Web 是否可访问

```bash
curl http://127.0.0.1:18000/
```

如果是组内直连模式，再从另一台内网机器测：

```bash
curl http://<服务器内网IP>:18000/
```

### 5.4 固定回归

```bash
python3 scripts/run_fulltext_regression.py
```

### 5.5 实际演示链路

建议至少手动走一遍：

1. Discover
2. 页面上传 PDF
3. Analyze Selected
4. 查看结果
5. 下载导出

---

## 6. 当前最小交付结论

按当前项目状态，已经具备：

- Web 页面运行
- 内网环境下演示
- Web 上传 PDF
- 后台任务执行
- 固定 fulltext regression

但仍不包含：

- 队列
- 取消任务
- 跨进程恢复
- nginx / docker / 生产级托管

所以它适合作为：

- 组内演示环境
- 小规模内网试用环境

而不是正式公网生产部署。
