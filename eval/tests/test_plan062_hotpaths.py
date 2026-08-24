import unittest

from rondo_eval.plan062_hotpaths import Plan062BenchmarkError
from rondo_eval.plan062_hotpaths import parse_divan_output


def _fixture() -> str:
    lines = ["                fastest │ slowest │ median │ mean │ samples │ iters"]
    for group, values in (
        ("history_turns", (8, 32, 128)),
        ("tool_specs", (8, 32, 64)),
        ("unified_exec_bytes", (4096, 262144, 1048576)),
    ):
        lines.append(group)
        for value in values:
            lines.extend(
                [
                    f"│  ├─ {value}       10 ns │ 20 ns │ 15 ns │ 16 ns │ 20 │ 200",
                    "│  │  alloc:              │       │       │       │    │",
                    "│  │                      │       │ 3     │       │    │",
                    "│  │                      │       │ 1 KiB │       │    │",
                ]
            )
    return "\n".join(lines)


class Plan062DivanParserTests(unittest.TestCase):
    def test_parses_all_allowlisted_cases(self) -> None:
        parsed = parse_divan_output(_fixture())
        self.assertEqual(len(parsed), 9)
        self.assertEqual(parsed["history_turns_8"]["median_ns"], 15.0)
        self.assertEqual(parsed["tool_specs_64"]["alloc_count_median"], 3.0)
        self.assertEqual(
            parsed["unified_exec_bytes_1048576"]["alloc_bytes_median"], 1024.0
        )

    def test_rejects_partial_output(self) -> None:
        with self.assertRaisesRegex(Plan062BenchmarkError, "case mismatch"):
            parse_divan_output("history_turns\n├─ 8  1 ns │ 1 ns │ 1 ns │ 1 ns │ 1 │ 1")

    def test_rejects_unknown_units(self) -> None:
        with self.assertRaisesRegex(Plan062BenchmarkError, "unknown Divan time"):
            parse_divan_output(_fixture().replace("15 ns", "15 ticks", 1))


if __name__ == "__main__":
    unittest.main()
