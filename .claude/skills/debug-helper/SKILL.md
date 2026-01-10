---
name: debug-helper
description: Systematic debugging approach for identifying and fixing issues. Use when debugging, troubleshooting errors, or asking about bugs and problems.
allowed-tools: Read, Bash, Grep, Glob
---

# Debug Helper

提供系统化的调试方法来识别和修复问题。

## Debugging Process

### 1. 🔍 问题定位

首先收集信息：
- 错误信息是什么？
- 何时开始出现？
- 是否可以复现？步骤是什么？
- 最近有什么变更？

### 2. 📊 信息收集

```bash
# 查看日志
tail -n 100 /path/to/log

# 检查进程状态
ps aux | grep <process>

# 检查端口
netstat -tlnp | grep <port>

# 检查资源使用
top -b -n 1 | head -20
```

### 3. 🧪 假设与验证

1. 根据症状提出假设
2. 设计验证实验
3. 收集证据
4. 确认或排除假设
5. 重复直到找到根因

### 4. 🛠️ 常见问题类型

| 类型 | 典型症状 | 调试方向 |
|------|----------|----------|
| 空指针 | NullPointerException | 检查对象初始化 |
| 内存泄漏 | 逐渐变慢 | 分析堆内存 |
| 死锁 | 程序挂起 | 线程堆栈分析 |
| 竞态条件 | 间歇性失败 | 并发逻辑审查 |
| 配置错误 | 启动失败 | 检查配置文件 |

### 5. 📝 调试报告格式

```markdown
## 🐛 问题报告

### 现象
[描述观察到的问题]

### 复现步骤
1. [步骤1]
2. [步骤2]
3. [预期结果 vs 实际结果]

### 根因分析
[分析问题的根本原因]

### 解决方案
[具体的修复方案]

### 验证
[如何验证修复有效]

### 预防措施
[如何避免类似问题再次发生]
```

## Tips

- 使用二分法缩小问题范围
- 添加日志而不是猜测
- 检查最近的变更
- 简化问题，创建最小复现案例
- 休息一下，换个角度思考
