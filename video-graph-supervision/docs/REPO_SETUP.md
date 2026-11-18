# 仓库建立

建议名称 video-graph-supervision。当前未创建远端、未推送、未通知任何合作方。

1. 将 repo/ 内容作为新仓库根，先阅读 HANDOFF 与 README。
2. GitHub 建立合作仓库并邀请学长。建议初始私有，以便核对数据和第三方源码的分享范围。
3. 本地执行以下命令；URL 换成实际仓库：

```bash
git init -b main
git add .
git status --short
git commit -m "Add graph supervision baseline and research handoff"
git remote add origin <YOUR_REPOSITORY_URL>
git push -u origin main
```

artifacts/ 默认被忽略，不会由 git add . 纳入。两个 ZIP 随交接包提供，可通过合作附件分享，并在项目仓库记录位置和 SHA256。
原始 MP4、权重及未来运行输出同样不放普通 Git 历史。
legacy_src/ 是原代码快照，无原 Git 历史；20d5065 为来源提交标识，不等于本次新仓库提交。
不自动赋予第三方数据或历史代码新的开源许可证，原 reference_sources/ 许可保留。

推荐先开三个 issue：baseline reproduction、graph/QA evidence quality、paired pseudolabel evaluation。训练 issue 在质量结果后启动。
