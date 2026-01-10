---
name: test-writer
description: Writes comprehensive test cases following testing best practices. Use when writing tests, creating unit tests, or asking about test coverage.
allowed-tools: Read, Write, Bash
---

# Test Writer

编写全面的测试用例，遵循测试最佳实践。

## Testing Principles

### AAA Pattern (Arrange-Act-Assert)

```python
def test_user_creation():
    # Arrange: 准备测试数据
    user_data = {"name": "Alice", "email": "alice@example.com"}
    
    # Act: 执行被测试的操作
    user = User.create(**user_data)
    
    # Assert: 验证结果
    assert user.name == "Alice"
    assert user.email == "alice@example.com"
    assert user.id is not None
```

## Test Categories

### 1. Unit Tests

测试单个函数或方法的行为：

```python
import pytest

class TestCalculator:
    def test_add_positive_numbers(self):
        assert add(2, 3) == 5
    
    def test_add_negative_numbers(self):
        assert add(-1, -1) == -2
    
    def test_add_with_zero(self):
        assert add(5, 0) == 5
```

### 2. Edge Cases

```python
class TestEdgeCases:
    def test_empty_input(self):
        assert process([]) == []
    
    def test_none_input(self):
        with pytest.raises(TypeError):
            process(None)
    
    def test_maximum_value(self):
        assert process([sys.maxsize]) == expected
```

### 3. Mocking

```python
from unittest.mock import Mock, patch

def test_api_call():
    with patch('module.requests.get') as mock_get:
        mock_get.return_value.json.return_value = {"data": "test"}
        
        result = fetch_data()
        
        assert result == {"data": "test"}
        mock_get.assert_called_once()
```

### 4. Fixtures (pytest)

```python
import pytest

@pytest.fixture
def sample_user():
    return User(name="Test", email="test@example.com")

@pytest.fixture
def db_session():
    session = create_session()
    yield session
    session.rollback()

def test_user_save(sample_user, db_session):
    db_session.add(sample_user)
    db_session.commit()
    assert sample_user.id is not None
```

## Test Coverage Checklist

- [ ] Happy path (正常流程)
- [ ] Error handling (错误处理)
- [ ] Boundary conditions (边界条件)
- [ ] Null/empty inputs
- [ ] Concurrent access (如适用)
- [ ] Performance (性能测试)

## Best Practices

- 测试名称要描述性：`test_should_return_error_when_input_is_invalid`
- 一个测试只验证一件事
- 测试要独立，不依赖执行顺序
- 使用有意义的断言消息
- 保持测试快速
- 避免测试实现细节，测试行为

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test
pytest tests/test_module.py::TestClass::test_method

# Verbose output
pytest -v
```
