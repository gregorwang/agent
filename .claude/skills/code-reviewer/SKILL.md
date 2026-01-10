---
name: code-reviewer
description: Provides systematic code review with focus on quality, security, and best practices. Use when reviewing code, doing PR reviews, or asking for code feedback.
allowed-tools: Read, Grep, Glob
---

# Code Reviewer

提供系统化的代码审查，关注代码质量、安全性和最佳实践。

## Review Checklist

### 1. 代码质量
- [ ] 代码可读性和命名规范
- [ ] 函数/方法职责单一
- [ ] 适当的注释和文档
- [ ] 代码复用性
- [ ] 错误处理是否完整

### 2. 安全性
- [ ] 输入验证
- [ ] SQL 注入风险
- [ ] XSS 漏洞
- [ ] 敏感数据处理
- [ ] 认证和授权

### 3. 性能
- [ ] 算法复杂度
- [ ] 数据库查询优化
- [ ] 内存使用
- [ ] 缓存策略

### 4. 测试
- [ ] 测试覆盖率
- [ ] 边界条件测试
- [ ] 错误路径测试

## Review Format

```markdown
## 📋 代码审查报告

### 概述
[简要描述审查的代码范围和目的]

### ✅ 优点
- [列出代码的优点]

### ⚠️ 需要改进
- [列出需要改进的地方，按优先级排序]

### 🔒 安全问题
- [列出任何安全相关的问题]

### 💡 建议
- [提供具体的改进建议和代码示例]

### 总结
[整体评价和下一步行动建议]
```

## Best Practices

- 保持专业和建设性的语气
- 提供具体的改进建议，不只是指出问题
- 区分"必须修改"和"建议修改"
- 认可好的代码实践
