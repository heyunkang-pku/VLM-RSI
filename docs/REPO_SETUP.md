# 仓库协作与附件发布

当前仓库：[heyunkang-pku/VLM-RSI](https://github.com/heyunkang-pku/VLM-RSI)，默认分支 `main`。项目目录已整理到仓库根，接手者从克隆开始，无需重新 `git init` 或另建嵌套仓库。

## 接手

```bash
git clone https://github.com/heyunkang-pku/VLM-RSI.git
cd VLM-RSI
python3 scripts/score_v2.py
```

新输出在 `runs/v2-review/`，原归档结果在 `results/`。获取视觉材料见 [DATA.md](DATA.md)。

## 日常修改

从最新 `main` 创建工作分支，提交后推送并建立 Pull Request，便于双方查看改动。提交前核对 `git status`，让不同协议或实验使用独立版本和运行目录。

## 发布完整数据附件（维护者）

本次检查时仓库 Releases 无附件。已有两个原始 ZIP 可作为一次交接 Release 的附件上传：

1. 仓库网页 → Releases → Draft a new release。
2. 新建 tag，例如 `handoff-20261118`，目标分支选择 `main`。
3. 附上 `STEP_EVENT_MCQ_V2_DATA.zip` 和 `STEP_EVENT_MCQ_V2_BLIND_REVIEW.zip`，确认 [DATA.md](DATA.md) 的哈希。
4. 发布后将实际下载地址补入 DATA.md，替换“联系维护者获取”的状态说明。

artifacts/、原始媒体、模型权重和运行目录已由根 `.gitignore` 排除。Release 附件不会自动出现在 `git clone` 得到的目录里，接手者需另行下载。

## 邀请合作方

仓库 Settings → Collaborators / Collaborators & teams → Add people，邀请对方 GitHub 账号。

legacy_src/ 是源自 20d5065 的历史快照，没有原仓库 Git 历史；该标识不是本仓库的提交。
原第三方许可信息保留，不为素材或历史源码统一补写新许可证。
