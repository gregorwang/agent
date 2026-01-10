---
name: doc-generator
description: Generates comprehensive documentation including README, docstrings, and API docs. Use when creating documentation, writing README files, or adding code comments.
allowed-tools: Read, Write, Glob
---

# Doc Generator

生成全面的文档，包括 README、docstrings 和 API 文档。

## Documentation Types

### 1. README.md 模板

```markdown
# Project Name

Brief description of the project.

## Features

- Feature 1
- Feature 2

## Installation

\`\`\`bash
pip install package-name
\`\`\`

## Quick Start

\`\`\`python
# Example usage
from package import main
main()
\`\`\`

## Configuration

| Option | Description | Default |
|--------|-------------|---------|
| option1 | Description | value |

## API Reference

See [API.md](docs/API.md) for full documentation.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License
```

### 2. Python Docstring (Google Style)

```python
def function_name(param1: str, param2: int = 0) -> bool:
    """Brief description of function.

    Longer description if needed, explaining the purpose
    and any important details.

    Args:
        param1: Description of first parameter.
        param2: Description of second parameter. Defaults to 0.

    Returns:
        Description of return value.

    Raises:
        ValueError: When param1 is empty.
        TypeError: When param2 is not an integer.

    Example:
        >>> function_name("test", 42)
        True
    """
```

### 3. Class Documentation

```python
class ClassName:
    """Brief class description.

    Longer description explaining the purpose and usage of the class.

    Attributes:
        attr1: Description of attribute 1.
        attr2: Description of attribute 2.

    Example:
        >>> obj = ClassName()
        >>> obj.method()
    """
```

## Best Practices

- 保持简洁但完整
- 使用示例说明用法
- 记录异常和边界情况
- 保持文档与代码同步更新
- 使用一致的风格和格式

## Generated Doc Checklist

- [ ] 项目概述清晰
- [ ] 安装步骤完整
- [ ] 有使用示例
- [ ] API 文档完整
- [ ] 配置选项说明
- [ ] 贡献指南
- [ ] 许可证信息
