# 开发与 Git 协作

所有命令均在仓库根目录 `DSAI5205-rag-travel-project/` 执行。

## 获取最新代码并开始新功能

先运行 `git status`，确认没有未提交修改；有修改时，先在当前功能分支提交，或用 `git stash push -u` 暂存后再切换。

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/your-feature
```

将 `feat/your-feature` 替换为本次功能的分支名，例如 `feat/travel-chat` 或 `feat/backend-api`。

如果刚才使用了 stash，切换到要继续工作的分支后，再用 `git stash pop` 恢复；出现冲突时先解决冲突。

## 提交自己的修改

```bash
git status
git add 你这次修改的文件或目录
git diff --cached
git commit -m "feat: describe this change"
git push -u origin HEAD
```

`git add` 后面的中文是占位说明，需要替换为实际路径，例如 `backend/`。在提交前检查暂存的内容。

## 合并与同步

1. 在 GitHub 为自己的分支创建 Pull Request，目标分支选择 `main`。
2. 写明修改内容、验证方式以及是否影响接口或配置。
3. 由组员检查后合并，`main` 保持可运行。
4. 其他组员更新本地 `main`，再从它创建下一个功能分支。

仓库搭建阶段尚无可运行应用；应用接入后，将启动与验证步骤补充到对应目录的 README。

## 团队约定

- 前端主要修改 `frontend/`，后端主要修改 `backend/`。
- 接口或配置格式改变时，同时更新相应文档和 `.env.example`。
- 同一个配置文件需要多人修改时，先协调修改范围。
- 遇到拉取失败或冲突，先看提示并保留本地修改，避免覆盖他人的提交。
