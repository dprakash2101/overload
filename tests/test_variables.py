from __future__ import annotations

from overload.collection.models import CollectionVariable
from overload.collection.variables import VariableContext


class TestVariableResolution:
    def test_simple_substitution(self) -> None:
        ctx = VariableContext(runtime_vars={"host": "api.example.com"})
        assert ctx.resolve("https://{{host}}/users") == "https://api.example.com/users"

    def test_scope_precedence_runtime_wins(self) -> None:
        ctx = VariableContext(
            collection_vars=[CollectionVariable("token", "coll-token")],
            environment_vars={"token": "env-token"},
            runtime_vars={"token": "runtime-token"},
        )
        assert ctx.resolve("{{token}}") == "runtime-token"

    def test_scope_precedence_env_over_collection(self) -> None:
        ctx = VariableContext(
            collection_vars=[CollectionVariable("token", "coll-token")],
            environment_vars={"token": "env-token"},
        )
        assert ctx.resolve("{{token}}") == "env-token"

    def test_collection_fallback(self) -> None:
        ctx = VariableContext(
            collection_vars=[CollectionVariable("token", "coll-token")],
        )
        assert ctx.resolve("{{token}}") == "coll-token"

    def test_unresolved_leaves_placeholder(self) -> None:
        ctx = VariableContext()
        result = ctx.resolve("{{missing}}")
        assert result == "{{missing}}"
        assert "missing" in ctx.unresolved

    def test_multiple_variables(self) -> None:
        ctx = VariableContext(runtime_vars={"host": "api.com", "version": "v2"})
        assert ctx.resolve("https://{{host}}/{{version}}/data") == "https://api.com/v2/data"

    def test_recursive_resolution(self) -> None:
        ctx = VariableContext(runtime_vars={
            "base_url": "https://{{host}}/api",
            "host": "example.com",
        })
        assert ctx.resolve("{{base_url}}") == "https://example.com/api"

    def test_no_template_passthrough(self) -> None:
        ctx = VariableContext()
        assert ctx.resolve("plain text") == "plain text"
        assert ctx.resolve("") == ""

    def test_resolve_dict(self) -> None:
        ctx = VariableContext(runtime_vars={"key": "X-Api-Key", "val": "abc123"})
        result = ctx.resolve_dict({"{{key}}": "{{val}}"})
        assert result == {"X-Api-Key": "abc123"}

    def test_set_variable(self) -> None:
        ctx = VariableContext()
        ctx.set_variable("new_var", "value")
        assert ctx.resolve("{{new_var}}") == "value"

    def test_get_all_variables(self) -> None:
        ctx = VariableContext(
            collection_vars=[CollectionVariable("a", "1")],
            environment_vars={"b": "2"},
            runtime_vars={"c": "3"},
        )
        all_vars = ctx.get_all_variables()
        assert all_vars == {"a": "1", "b": "2", "c": "3"}


class TestDynamicVariables:
    def test_random_int(self) -> None:
        ctx = VariableContext()
        result = ctx.resolve("{{$randomInt}}")
        assert result.isdigit()

    def test_guid(self) -> None:
        ctx = VariableContext()
        result = ctx.resolve("{{$guid}}")
        assert len(result) == 36
        assert result.count("-") == 4

    def test_timestamp(self) -> None:
        ctx = VariableContext()
        result = ctx.resolve("{{$timestamp}}")
        assert result.isdigit()
        assert int(result) > 1_000_000_000

    def test_random_boolean(self) -> None:
        ctx = VariableContext()
        result = ctx.resolve("{{$randomBoolean}}")
        assert result in ("true", "false")

    def test_random_email(self) -> None:
        ctx = VariableContext()
        result = ctx.resolve("{{$randomEmail}}")
        assert "@example.com" in result


class TestEnvironmentParsing:
    def test_parse_environment(self) -> None:
        from overload.collection.environment import parse_environment

        data = {
            "name": "Dev",
            "values": [
                {"key": "host", "value": "dev.api.com", "enabled": True},
                {"key": "disabled_var", "value": "skip", "enabled": False},
                {"key": "token", "value": "abc"},
            ],
        }
        env = parse_environment(data)
        assert env == {"host": "dev.api.com", "token": "abc"}
        assert "disabled_var" not in env

    def test_parse_environment_from_file(self, tmp_path) -> None:
        import json

        from overload.collection.environment import parse_environment

        data = {"values": [{"key": "k", "value": "v"}]}
        path = tmp_path / "env.json"
        path.write_text(json.dumps(data))
        env = parse_environment(str(path))
        assert env == {"k": "v"}
