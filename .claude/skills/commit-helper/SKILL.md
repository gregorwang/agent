---
name: commit-helper
description: Generates clear, conventional commit messages from git diffs. Use when writing commit messages, reviewing staged changes, or asking about git commits.
allowed-tools: Bash, Read
---

# Commit Helper

帮助生成清晰、规范的 Git 提交信息。

## Instructions

1. **分析变更**: 首先运行 `git diff --staged` 查看暂存的更改
2. **理解上下文**: 分析文件类型、修改范围和目的
3. **生成提交信息**: 按照以下格式生成

## Commit Message Format

使用 Conventional Commits 格式：

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

- `feat`: 新功能
- `fix`: Bug 修复
- `docs`: 文档更新
- `style`: 代码格式（不影响代码运行的变动）
- `refactor`: 重构（既不是新功能也不是修复 bug）
- `perf`: 性能优化
- `test`: 测试相关
- `chore`: 构建过程或辅助工具的变动

## Best Practices

- 标题行不超过 50 字符
- 使用现在时态（"Add feature" 而不是 "Added feature"）
- 正文每行不超过 72 字符
- 解释 **什么** 和 **为什么**，而不是 **怎么做**

## Example

```
feat(auth): add OAuth2 login support

- Implement Google OAuth2 authentication flow
- Add token refresh mechanism
- Create user session management

Closes #123
```
