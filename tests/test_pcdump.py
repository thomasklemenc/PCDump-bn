import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def load_plugin():
    binaryninja = types.ModuleType("binaryninja")
    binaryview = types.ModuleType("binaryninja.binaryview")
    enums = types.ModuleType("binaryninja.enums")
    function = types.ModuleType("binaryninja.function")
    interaction = types.ModuleType("binaryninja.interaction")
    lineardisassembly = types.ModuleType("binaryninja.lineardisassembly")
    log = types.ModuleType("binaryninja.log")
    plugin = types.ModuleType("binaryninja.plugin")
    typeprinter = types.ModuleType("binaryninja.typeprinter")

    class BinaryView:
        pass

    class Function:
        pass

    class BackgroundTaskThread:
        def __init__(self, message, can_cancel):
            self.message = message
            self.can_cancel = can_cancel
            self.progress = ""

        def start(self):
            self.run()

    class PluginCommand:
        @staticmethod
        def register_for_address(name, description, callback):
            return None

    class FakeTypePrinter:
        default = None

    binaryview.BinaryView = BinaryView
    enums.DisassemblyOption = types.SimpleNamespace(
        ShowAddress=object(), WaitForIL=object())
    enums.FunctionAnalysisSkipOverride = types.SimpleNamespace(
        NeverSkipFunctionAnalysis=object())
    function.DisassemblySettings = type("DisassemblySettings", (), {})
    function.Function = Function
    interaction.get_directory_name_input = lambda prompt: None
    lineardisassembly.LinearViewCursor = type("LinearViewCursor", (), {})
    lineardisassembly.LinearViewObject = type("LinearViewObject", (), {})
    log.log_alert = lambda message: None
    log.log_error = lambda message: None
    log.log_info = lambda message: None
    log.log_warn = lambda message: None
    plugin.BackgroundTaskThread = BackgroundTaskThread
    plugin.PluginCommand = PluginCommand
    typeprinter.TypePrinter = FakeTypePrinter

    modules = {
        "binaryninja": binaryninja,
        "binaryninja.binaryview": binaryview,
        "binaryninja.enums": enums,
        "binaryninja.function": function,
        "binaryninja.interaction": interaction,
        "binaryninja.lineardisassembly": lineardisassembly,
        "binaryninja.log": log,
        "binaryninja.plugin": plugin,
        "binaryninja.typeprinter": typeprinter,
    }

    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(
            "pcdump_under_test", REPOSITORY_ROOT / "__init__.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


class FakeTypeMapping:
    def __init__(self, entries):
        self.entries = entries

    def items(self):
        return iter(self.entries)


class PseudoCDumpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pcdump = load_plugin()

    def test_user_defined_types_exclude_auto_types_in_dependency_order(self):
        type_entries = [
            ("base_t", object()),
            ("platform_t", object()),
            ("derived_t", object()),
        ]
        bv = types.SimpleNamespace(
            dependency_sorted_types=FakeTypeMapping(type_entries),
            is_type_auto_defined=lambda name: name == "platform_t",
        )

        result = self.pcdump.get_user_defined_types(bv)

        self.assertEqual(
            ["base_t", "derived_t"],
            [name for name, _ in result],
        )

    def test_type_header_uses_only_supplied_user_types(self):
        printer = unittest.mock.Mock()
        self.pcdump.TypePrinter.default = printer
        bv = object()
        user_types = [("custom_t", object())]
        printer.print_all_types.return_value = "typedef int custom_t;\n"

        result = self.pcdump.get_user_type_header(bv, user_types)

        self.assertEqual("typedef int custom_t;\n", result)
        printer.print_all_types.assert_called_once_with(user_types, bv)

    def test_run_writes_shared_header_and_includes_it_from_c_files(self):
        function = types.SimpleNamespace(start=0x1000)
        symbol = types.SimpleNamespace(short_name="target")
        bv = types.SimpleNamespace(
            file=types.SimpleNamespace(filename="sample.bin"),
            functions=[function],
            get_symbol_at=lambda address: symbol,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory)
            dump = self.pcdump.PseudoCDump(
                bv, "Dumping", str(output_directory))
            dump._PseudoCDump__create_directory = (
                lambda: str(output_directory))

            with patch.object(
                    self.pcdump, "get_user_defined_types",
                    return_value=[("custom_t", object())]), patch.object(
                    self.pcdump, "get_user_type_header",
                    return_value="typedef int custom_t;\n"), patch.object(
                    self.pcdump, "force_analysis"), patch.object(
                    self.pcdump, "get_pseudo_c",
                    return_value="custom_t target(void)\n{\n    return 0;\n}\n"):
                dump.run()

            self.assertEqual(
                "typedef int custom_t;\n",
                (output_directory / "types.h").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                '#include "types.h"\n\n'
                "custom_t target(void)\n{\n    return 0;\n}\n",
                (output_directory / "target.c").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
