"""对照 OpenAPI 检查状态码、必填字段和基础类型。"""

from __future__ import annotations

from typing import Any


WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def find_operation(spec: dict, method: str, path: str) -> dict | None:
    paths = spec.get("paths") or {}
    method_l = method.lower()
    if path in paths and method_l in paths[path]:
        return paths[path][method_l]
    for template, ops in paths.items():
        if _match(template, path) and method_l in ops:
            return ops[method_l]
    return None


def _match(template: str, path: str) -> bool:
    t_parts = template.strip("/").split("/")
    p_parts = path.strip("/").split("/")
    if len(t_parts) != len(p_parts):
        return False
    for left, right in zip(t_parts, p_parts, strict=True):
        if left.startswith("{") and left.endswith("}"):
            continue
        if left != right:
            return False
    return True


def expected_status(op: dict, default: int) -> set[int]:
    codes = set()
    for key in (op.get("responses") or {}):
        if str(key).isdigit():
            codes.add(int(key))
    return codes or {default}


def schema_of(op: dict, status: int) -> dict | None:
    responses = op.get("responses") or {}
    raw = responses.get(str(status)) or responses.get("default")
    if not raw:
        return None
    content = raw.get("content") or {}
    json_body = content.get("application/json") or {}
    return json_body.get("schema")


def unwrap_schema(schema: dict | None, spec: dict) -> dict | None:
    return _unwrap(schema, spec)


def _unwrap(schema: dict | None, spec: dict) -> dict | None:
    if not schema:
        return None
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return (spec.get("components") or {}).get("schemas", {}).get(name)
    if "allOf" in schema:
        merged: dict = {"properties": {}, "required": []}
        for part in schema["allOf"]:
            item = _unwrap(part, spec) or {}
            merged["properties"].update(item.get("properties") or {})
            merged["required"].extend(item.get("required") or [])
            merged["type"] = item.get("type", merged.get("type"))
        return merged
    return schema


def check_value(value: Any, schema: dict | None, spec: dict, path: str) -> list[str]:
    errors: list[str] = []
    schema = _unwrap(schema, spec)
    if not schema:
        return errors
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            return [f"{path} 应为对象"]
        required = schema.get("required") or []
        props = schema.get("properties") or {}
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key} 缺失")
        for key, child in props.items():
            if key in value:
                errors.extend(check_value(value[key], child, spec, f"{path}.{key}"))
        return errors
    if expected == "array":
        if not isinstance(value, list):
            return [f"{path} 应为数组"]
        item_schema = schema.get("items")
        for i, item in enumerate(value):
            errors.extend(check_value(item, item_schema, spec, f"{path}[{i}]"))
        return errors
    if expected == "string" and not isinstance(value, str):
        errors.append(f"{path} 应为字符串")
    if expected == "integer" and not isinstance(value, int):
        errors.append(f"{path} 应为整数")
    if expected == "number" and not isinstance(value, (int, float)):
        errors.append(f"{path} 应为数字")
    if expected == "boolean" and not isinstance(value, bool):
        errors.append(f"{path} 应为布尔")
    if schema.get("format") == "date-time" and isinstance(value, str) and "T" not in value:
        errors.append(f"{path} 不是日期时间")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} 不在枚举内")
    return errors


def validate_call(spec: dict, method: str, path: str, status: int, body: Any) -> list[str]:
    op = find_operation(spec, method, path)
    if op is None:
        return [f"OpenAPI 中没有 {method} {path}"]
    allowed = expected_status(op, status)
    errors: list[str] = []
    if allowed and status not in allowed:
        errors.append(f"状态码 {status} 不在声明 {sorted(allowed)} 中")
    if status == 204 and body not in (None, "", {}, b""):
        errors.append("204 不应有响应体")
    schema = schema_of(op, status)
    if schema and status != 204:
        errors.extend(check_value(body, schema, spec, "$"))
    return errors
